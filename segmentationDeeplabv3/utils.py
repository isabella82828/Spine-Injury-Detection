import numpy as np
import cv2
import torch
import os
import matplotlib.pyplot as plt
from PIL import Image

from torchvision import transforms
from config import (
    VIS_LABEL_MAP as viz_map
)

plt.style.use('ggplot')

def set_class_values(all_classes, classes_to_train):
    """
    This (`class_values`) assigns a specific class label to the each of the classes.
    For example, `animal=0`, `archway=1`, and so on.

    :param all_classes: List containing all class names.
    :param classes_to_train: List containing class names to train.
    """
    class_values = [all_classes.index(cls.lower()) for cls in classes_to_train]
    return class_values

def get_label_mask(mask, class_values, label_colors_list):
    """
    This function encodes the pixels belonging to the same class
    in the image into the same label

    :param mask: NumPy array, segmentation mask.
    :param class_values: List containing class values, e.g car=0, bus=1.
    :param label_colors_list: List containing RGB color value for each class.
    """
    label_mask = np.zeros((mask.shape[0], mask.shape[1]), dtype=np.uint8)
    for value in class_values:
        for ii, label in enumerate(label_colors_list):
            if value == label_colors_list.index(label):
                label = np.array(label)
                label_mask[np.where(np.all(mask == label, axis=-1))[:2]] = value
    label_mask = label_mask.astype(int)
    return label_mask

class EarlyStopping:
    """Early stops the training if validation loss doesn't improve after a given patience."""
    def __init__(self, patience=20, verbose=False, delta=0):
        """
        Args:
            patience (int): How long to wait after last time validation loss improved.
                            Default: 7
            verbose (bool): If True, prints a message for each validation loss improvement. 
                            Default: False
            delta (float): Minimum change in the monitored quantity to qualify as an improvement.
                           Default: 0
        """
        self.patience = patience
        self.verbose = verbose
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.val_loss_min = float('inf')
        self.delta = delta

    def __call__(self, val_loss, model):

        score = -val_loss

        if self.best_score is None:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
        elif score < self.best_score + self.delta:
            self.counter += 1
            print(f'EarlyStopping counter: {self.counter} out of {self.patience}')
            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
            self.counter = 0

    def save_checkpoint(self, val_loss, model):
        """Saves model when validation loss decrease."""
        if self.verbose:
            print(f'Validation loss decreased ({self.val_loss_min:.6f} --> {val_loss:.6f}).  Saving model ...')
        torch.save(model.state_dict(), 'checkpoint.pt')
        self.val_loss_min = val_loss

def draw_translucent_seg_maps(
    data, 
    output, 
    epoch, 
    i, 
    val_seg_dir, 
    label_colors_list,
):
    """
    This function color codes the segmentation maps that is generated while
    validating. THIS IS NOT TO BE CALLED FOR SINGLE IMAGE TESTING
    """
    alpha = 1 # how much transparency
    beta = 0.6 # alpha + beta should be 1
    gamma = 0 # contrast

    seg_map = output[0] # use only one output from the batch
    seg_map = torch.argmax(seg_map.squeeze(), dim=0).detach().cpu().numpy()

    image = data[0]
    image = np.array(image.cpu())
    image = np.transpose(image, (1, 2, 0))
    # unnormalize the image (important step)
    mean = np.array([0.45734706, 0.43338275, 0.40058118])
    std = np.array([0.23965294, 0.23532275, 0.2398498])
    image = std * image + mean
    image = np.array(image, dtype=np.float32)
    image = image * 255

    red_map = np.zeros_like(seg_map).astype(np.uint8)
    green_map = np.zeros_like(seg_map).astype(np.uint8)
    blue_map = np.zeros_like(seg_map).astype(np.uint8)


    for label_num in range(0, len(label_colors_list)):
        index = seg_map == label_num
        red_map[index] = np.array(viz_map)[label_num, 0]
        green_map[index] = np.array(viz_map)[label_num, 1]
        blue_map[index] = np.array(viz_map)[label_num, 2]
        
    rgb = np.stack([red_map, green_map, blue_map], axis=2)
    rgb = np.array(rgb, dtype=np.float32)
    # convert color to BGR format for OpenCV
    rgb = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    # cv2.imshow('rgb', rgb)
    # cv2.waitKey(0)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    cv2.addWeighted(image, alpha, rgb, beta, gamma, image)
    cv2.imwrite(f"{val_seg_dir}/e{epoch}_b{i}.jpg", image)

class SaveBestModel:
    """
    Class to save the best model while training. If the current epoch's 
    validation loss is less than the previous least less, then save the
    model state.
    """
    def __init__(self, best_valid_loss=float('inf')):
        self.best_valid_loss = best_valid_loss
        
    def __call__(
        self, current_valid_loss, epoch, model, out_dir, name='model'
    ):
        if current_valid_loss < self.best_valid_loss:
            self.best_valid_loss = current_valid_loss
            print(f"\nBest validation loss: {self.best_valid_loss}")
            print(f"\nSaving best model for epoch: {epoch+1}\n")
            torch.save({
                'epoch': epoch+1,
                'model_state_dict': model.state_dict(),
                }, os.path.join(out_dir, 'best_'+name+'.pth'))

class SaveBestModelIOU:
    """
    Class to save the best model while training. If the current epoch's 
    IoU is higher than the previous highest, then save the
    model state.
    """
    def __init__(self, best_iou=float(0)):
        self.best_iou = best_iou
        
    def __call__(self, current_iou, epoch, model, out_dir, name='model'):
        if current_iou > self.best_iou:
            self.best_iou = current_iou
            print(f"\nBest validation IoU: {self.best_iou}")
            print(f"\nSaving best model for epoch: {epoch+1}\n")
            torch.save({
                'epoch': epoch+1,
                'model_state_dict': model.state_dict(),
                }, os.path.join(out_dir, 'best_'+name+'.pth'))

def save_model(epochs, model, optimizer, criterion, out_dir, name='model'):
    """
    Function to save the trained model to disk.
    """
    torch.save({
                'epoch': epochs,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'loss': criterion,
                }, os.path.join(out_dir, name+'.pth'))

def save_plots(
    train_acc, valid_acc, 
    train_loss, valid_loss, 
    train_miou, valid_miou, 
    out_dir
):
    """
    Function to save the loss and accuracy plots to disk.
    """
    # Accuracy plots.
    plt.figure(figsize=(10, 7))
    plt.plot(
        train_acc, color='tab:blue', linestyle='-', 
        label='train accuracy'
    )
    plt.plot(
        valid_acc, color='tab:red', linestyle='-', 
        label='validataion accuracy'
    )
    plt.xlabel('Epochs')
    plt.ylabel('Accuracy')
    plt.legend()
    plt.savefig(os.path.join(out_dir, 'accuracy.png'))
    
    # Loss plots.
    plt.figure(figsize=(10, 7))
    plt.plot(
        train_loss, color='tab:blue', linestyle='-', 
        label='train loss'
    )
    plt.plot(
        valid_loss, color='tab:red', linestyle='-', 
        label='validataion loss'
    )
    plt.xlabel('Epochs')
    plt.ylabel('Loss')
    plt.legend()
    plt.savefig(os.path.join(out_dir, 'loss.png'))

    # mIOU plots.
    plt.figure(figsize=(10, 7))
    plt.plot(
        train_miou, color='tab:blue', linestyle='-', 
        label='train mIoU'
    )
    plt.plot(
        valid_miou, color='tab:red', linestyle='-', 
        label='validataion mIoU'
    )
    plt.xlabel('Epochs')
    plt.ylabel('mIoU')
    plt.legend()
    plt.savefig(os.path.join(out_dir, 'miou.png'))

class ConvertToRGB:
    def __call__(self, image):
        if image.mode != 'RGB':
            return image.convert('RGB')
        return image

# Define the torchvision image transforms
transform = transforms.Compose([
    ConvertToRGB(),  # Ensure all images are in RGB
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])


def get_segment_labels(image, model, device):
    # transform the image to tensor and load into computation device
    image = transform(image).to(device)
    image = image.unsqueeze(0) # add a batch dimension
    with torch.no_grad():
        outputs = model(image)
    return outputs

def draw_segmentation_map(outputs):
    labels = torch.argmax(outputs.squeeze(), dim=0).detach().cpu().numpy()

    # create Numpy arrays containing zeros
    # later to be used to fill them with respective red, green, and blue pixels
    red_map = np.zeros_like(labels).astype(np.uint8)
    green_map = np.zeros_like(labels).astype(np.uint8)
    blue_map = np.zeros_like(labels).astype(np.uint8)
    
    for label_num in range(0, len(viz_map)):
        index = labels == label_num
        red_map[index] = np.array(viz_map)[label_num, 0]
        green_map[index] = np.array(viz_map)[label_num, 1]
        blue_map[index] = np.array(viz_map)[label_num, 2]
        
    segmentation_map = np.stack([red_map, green_map, blue_map], axis=2)
    return segmentation_map

def image_overlay(image, segmented_image):
    alpha = 0.8 # transparency for the original image
    beta = 0.35 # transparency for the segmentation map
    gamma = 0 # scalar added to each sum

    segmented_image = cv2.cvtColor(segmented_image, cv2.COLOR_RGB2BGR)
    image = np.array(image)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    cv2.addWeighted(image, alpha, segmented_image, beta, gamma, image)
    return image

# def overlay_image(img, mask):
#     image = Image.blend(img.convert('RGBA'), segmented_image.convert('RGBA'), alpha=0.35)
#     return image
