import os
from functools import partial

import torch
from accelerate import notebook_launcher
from accelerate.utils import set_seed
from torch import nn, optim
from torch.optim import lr_scheduler
from torchmetrics import ConfusionMatrix
from torchvision import transforms, datasets, models

from pytorch_thunder.trainer import Trainer


class TrainerWithMetrics(Trainer):
    def __init__(self, num_classes, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cm_metrics = ConfusionMatrix(num_classes=num_classes)

    def train_epoch_start(self):
        super().train_epoch_start()
        self.cm_metrics.to(self._eval_dataloader.device)

    def calculate_eval_batch_step(self, batch):
        batch_output = super().calculate_eval_batch_step(batch)

        preds = batch_output["model_outputs"].argmax(dim=-1)
        all_preds = self._accelerator.gather(preds)
        all_labels = self._accelerator.gather(batch[1])

        self.cm_metrics.update(all_preds, all_labels)

        return batch_output

    def eval_epoch_end(self):
        super().eval_epoch_end()

        cm = self.cm_metrics.compute()
        self.run_history.update_metric("confusion_matrix", cm.cpu())
        self.cm_metrics.reset()


def main():
    set_seed(42)

    # Data augmentation and normalization for training
    # Just normalization for validation
    data_transforms = {
        "train": transforms.Compose(
            [
                transforms.RandomResizedCrop(224),
                transforms.RandomHorizontalFlip(),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        ),
        "val": transforms.Compose(
            [
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        ),
    }

    # Create datasets
    data_dir = (
        r"C:\Users\hughesc\OneDrive - Microsoft\Documents\toy_data\hymenoptera_data"
    )
    data_dir = r"/home/chris/notebooks/hymenoptera_data/"

    image_datasets = {
        x: datasets.ImageFolder(os.path.join(data_dir, x), data_transforms[x])
        for x in ["train", "val"]
    }
    # Create model
    model = models.resnet18(pretrained=True)
    model.fc = nn.Linear(model.fc.in_features, len(image_datasets["train"].classes))

    # Define loss function
    loss_func = nn.CrossEntropyLoss()

    # Create optimizer and scheduler
    optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)
    exp_lr_scheduler = partial(lr_scheduler.StepLR, step_size=7, gamma=0.1)

    trainer = TrainerWithMetrics(
        num_classes=2,
        model=model,
        loss_func=loss_func,
        optimizer=optimizer,
        scheduler_type=exp_lr_scheduler,
    )

    trainer.train(
        train_dataset=image_datasets["train"],
        eval_dataset=image_datasets["val"],
        num_epochs=8,
        per_device_batch_size=4,
        fp16=True,
    )


if __name__ == "__main__":
    notebook_launcher(main, num_processes=2)
