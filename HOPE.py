# -*- coding: utf-8 -*-

from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

"""# Import Libraries"""

import numpy as np
import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.optim as optim
import torchvision.transforms as transforms
from utils.model import select_model
from utils.options import parse_args_function
from utils.dataset import Dataset
from position_evaluator import ZimEval
import position_evaluator

args = parse_args_function()

"""# Load Dataset"""

root = args.input_file

#mean = np.array([120.46480086, 107.89070987, 103.00262132])
#std = np.array([5.9113948 , 5.22646725, 5.47829601])

transform = transforms.Compose([transforms.Resize((224, 224)),
                                transforms.ToTensor()])

if args.train:
    trainset = Dataset(root=root, load_set='train', transform=transform)
    trainloader = torch.utils.data.DataLoader(trainset, batch_size=args.batch_size, shuffle=True, num_workers=16)
    
    print('Train files loaded')

if args.val:
    valset = Dataset(root=root, load_set='val', transform=transform)
    valloader = torch.utils.data.DataLoader(valset, batch_size=args.batch_size, shuffle=False, num_workers=8)
    
    print('Validation files loaded')

if args.test:
    testset = Dataset(root=root, load_set='test', transform=transform)
    testloader = torch.utils.data.DataLoader(testset, batch_size=args.batch_size, shuffle=False, num_workers=8)
    
    print('Test files loaded')

# Create evaluator
evaluator = ZimEval(num_kp=21)     

"""# Model"""

use_cuda = False
if args.gpu:
    use_cuda = True

model = select_model(args.model_def)

if use_cuda and torch.cuda.is_available():
    model = model.cuda()
    model = nn.DataParallel(model, device_ids=args.gpu_number)

"""# Load Snapshot"""

if args.pretrained_model != '':
    model.load_state_dict(torch.load(args.pretrained_model))
    losses = np.load(args.pretrained_model[:-4] + '-losses.npy').tolist()
    start = len(losses)
else:
    losses = []
    start = 0

"""# Optimizer"""

criterion = nn.MSELoss()
optimizer = optim.Adam(model.parameters(), lr=args.learning_rate)
scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=args.lr_step, gamma=args.lr_step_gamma)
scheduler.last_epoch = start
lambda_1 = 0.01
lambda_2 = 1

"""# Train"""

if args.train:
    print('Begin training the network...')
    
    for epoch in range(start, args.num_iterations):  # loop over the dataset multiple times
    
        running_loss = 0.0
        train_loss = 0.0
        for i, tr_data in enumerate(trainloader):
            # get the inputs
            inputs, labels2d, labels3d = tr_data
    
            # wrap them in Variable
            inputs = Variable(inputs)
            labels2d = Variable(labels2d)
            labels3d = Variable(labels3d)
            
            if use_cuda and torch.cuda.is_available():
                inputs = inputs.float().cuda(device=args.gpu_number[0])
                labels2d = labels2d.float().cuda(device=args.gpu_number[0])
                labels3d = labels3d.float().cuda(device=args.gpu_number[0])
    
            # zero the parameter gradients
            optimizer.zero_grad()
    
            # forward + backward + optimize
            outputs2d_init, outputs2d, outputs3d = model(inputs)
            loss2d_init = criterion(outputs2d_init, labels2d)
            loss2d = criterion(outputs2d, labels2d)
            loss3d = criterion(outputs3d, labels3d)
            loss = (lambda_1)*loss2d_init + (lambda_1)*loss2d + (lambda_2)*loss3d
            loss.backward()
            optimizer.step()
            
            # print statistics
            running_loss += loss.data
            train_loss += loss.data
            if (i+1) % args.log_batch == 0:    # print every log_iter mini-batches
                print('[%d, %5d] loss: %.5f' % (epoch + 1, i + 1, running_loss / args.log_batch))
                running_loss = 0.0
                
        if args.val and (epoch+1) % args.val_epoch == 0:
            val_loss = 0.0
            for v, val_data in enumerate(valloader):
                # get the inputs
                inputs, labels2d, labels3d = val_data
                
                # wrap them in Variable
                inputs = Variable(inputs)
                labels2d = Variable(labels2d)
                labels3d = Variable(labels3d)
        
                if use_cuda and torch.cuda.is_available():
                    inputs = inputs.float().cuda(device=args.gpu_number[0])
                    labels2d = labels2d.float().cuda(device=args.gpu_number[0])
                    labels3d = labels3d.float().cuda(device=args.gpu_number[0])
        
                outputs2d_init, outputs2d, outputs3d = model(inputs)
                
                loss2d_init = criterion(outputs2d_init, labels2d)
                loss2d = criterion(outputs2d, labels2d)
                loss3d = criterion(outputs3d, labels3d)
                loss = (lambda_1)*loss2d_init + (lambda_1)*loss2d + (lambda_2)*loss3d
                val_loss += loss.data
            print('val error: %.5f' % (val_loss / (v+1)))
        losses.append((train_loss / (i+1)).cpu().numpy())
        
        if (epoch+1) % args.snapshot_epoch == 0:
            torch.save(model.state_dict(), args.output_file+str(epoch+1)+'.pkl')
            np.save(args.output_file+str(epoch+1)+'-losses.npy', np.array(losses))

        # Decay Learning Rate
        scheduler.step()
    
    print('Finished Training')

"""# Test"""

if args.test:
    print('Begin testing the network...')
    
    running_loss = 0.0
    for i, ts_data in enumerate(testloader):
        # get the inputs
        inputs, labels2d, labels3d = ts_data
        
        # wrap them in Variable
        inputs = Variable(inputs)
        labels2d = Variable(labels2d)
        labels3d = Variable(labels3d)

        if use_cuda and torch.cuda.is_available():
            inputs = inputs.float().cuda(device=args.gpu_number[0])
            labels2d = labels2d.float().cuda(device=args.gpu_number[0])
            labels3d = labels3d.float().cuda(device=args.gpu_number[0])

        outputs2d_init, outputs2d, outputs3d = model(inputs)
        
        loss = criterion(outputs3d, labels3d)
        running_loss += loss.data
        
        evaluator.feed(labels3d, outputs3d, None)
        
        
        
        
    print('test error: %.5f' % (running_loss / (i+1)))
    epe_mean_all, epe_mean_joint, eqe_median, auc_all, pck_curve_all, threshholds = evaluator.get_measures(0.0, 0.050, 21)
    