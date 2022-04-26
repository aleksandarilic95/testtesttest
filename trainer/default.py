from logger.default import Logger
import torch
from metrics.map import mean_average_precision
import torchvision

class Trainer:
    def __init__(self, config, device, model, trainval_dataloaders, optimizer, lr_scheduler, logger):
        self.config = config
        self.device = device
        self.model = model.to(self.device)
        self.logger = logger
        self.train_dataloader = trainval_dataloaders['train']
        self.val_dataloader = trainval_dataloaders['val']
        self.optimizer = optimizer
        self.lr_scheduler = lr_scheduler

        self.iter_batch = 0
        self.iter = 1
        self.thresholds = [0.5, 0.55, 0.60, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]
        
        self.num_of_epochs = self.config['NUM_OF_EPOCHS']
        self.score_threshold = self.config['SCORE_THRESHOLD']
        self.nms_threshold = self.config['NMS_THRESHOLD']
        self.batch_size = self.config['BATCH_SIZE']

    def transform_input_target(self, inputs, targets):
        inputs = [input_.to(self.device) for input_ in inputs]

        labels = []
        for i in range(len(inputs)):
            d = {}
            targets[i][:,2:4] += targets[i][:,0:2]
            d['boxes'] = targets[i].to(self.device)
            d['labels'] = torch.ones(targets[i].shape[0], dtype = torch.int64).to(self.device)
            labels.append(d)

        return inputs, labels

    def train_epoch(self):
        self.model.train()
        
        loss = None
        
        for inputs, targets in self.train_dataloader:
            if len(inputs) == 0:
                continue

            inputs, targets = self.transform_input_target(inputs, targets)
            loss_dict = self.model(inputs, targets)
            loss = sum(loss for loss in loss_dict.values()).to("cpu")

            loss.backward(retain_graph = True)
            # print(f'Memory cached: {torch.cuda.memory_cached() / 1024 ** 2}')
            # print(f'Memory cached: {torch.cuda.memory_cached() / 1024 ** 2}')

            
            self.logger.add_scalar('train_loss', loss.item(), global_step = self.iter)
            self.logger.log_info('Iter {} train loss: {}'.format(self.iter, loss.item()))
            self.optimizer.step()
            self.optimizer.zero_grad()
            loss = None
            
            self.iter += 1

    def valid_epoch(self):
        print("In valid epoch")
        self.model.eval()

        gt_boxes = []
        pred_boxes = []
        train_idx = 0

        with torch.no_grad():
            for inputs, targets in self.val_dataloader:
                if len(inputs) == 0:
                    continue

                inputs, targets = self.transform_input_target(inputs, targets)

                outputs = self.model(inputs)

                if len(outputs[0]['scores']) > 0:
                    keep_indexes = torchvision.ops.nms(outputs[0]['boxes'], outputs[0]['scores'], self.nms_threshold)
                    for index in keep_indexes:
                        if len(outputs[0]['scores']) and outputs[0]['scores'][index] > self.score_threshold:
                            pred_box = [train_idx, outputs[0]['labels'][index], outputs[0]['scores'][index]] + outputs[0]['boxes'][index].tolist()
                            pred_boxes.append(pred_box)

                    for i in range(len(targets)):
                        for j in range(len(targets[i]['boxes'])):
                            gt_box = [train_idx, 1, 1] + targets[i]['boxes'][j].tolist()
                            gt_boxes.append(gt_box)

                    train_idx += 1
        scores = []
        for threshold in self.thresholds:
            scores.append(mean_average_precision(pred_boxes, gt_boxes, iou_threshold = threshold, num_classes = 2))
        mAP = sum(scores) / len(scores)
        
        return mAP


    def train(self):
        for epoch in range(self.num_of_epochs):
            self.logger.log_info('Starting training of epoch {}.'.format(epoch))
            self.train_epoch()
            mAP = self.valid_epoch()
            self.logger.log_info('Epoch {}: mAP @ 0.5:0.95:0.05: {}'.format(epoch, mAP))
            torch.save(self.model.state_dict(), 'out/model.pt')
