# -*- coding: utf-8 -*-
# @Author : lishouxian
# @Email : gzlishouxian@gmail.com
# @File : train.py
# @Software: PyCharm
from engines.models.BinaryPointer import BinaryPointer
from transformers import AdamW
from tqdm import tqdm
from torch.utils.data import DataLoader
from engines.data import DataGenerator
from engines.predict import Predictor
import json
import torch
import time
import os


def train(configs, device, logger):
    predictor = Predictor(configs, device, logger)
    train_file = configs.datasets_fold + '/' + configs.train_file
    dev_file = configs.datasets_fold + '/' + configs.dev_file
    train_data = json.load(open(train_file, encoding='utf-8'))
    dev_data = json.load(open(dev_file, encoding='utf-8'))
    train_data_generator = DataGenerator(configs, train_data, logger=logger)
    logger.info('dev_data_length:{}\n'.format(len(dev_data)))
    train_dataset = train_data_generator.prepare_data()
    loader = DataLoader(
        dataset=train_dataset,  # torch TensorDataset format
        batch_size=configs.batch_size,  # mini batch size
        shuffle=True,  # random shuffle for training
    )
    learning_rate = configs.learning_rate
    adam_epsilon = 1e-05
    num_labels = len(configs.class_name)
    model = BinaryPointer(hidden_size=768, num_labels=num_labels).to(device)
    params = list(model.parameters())
    optimizer = AdamW(params, lr=learning_rate, eps=adam_epsilon)
    loss_function = torch.nn.BCELoss(reduction='none')
    best_f1 = 0
    best_epoch = 0
    unprocessed = 0
    very_start_time = time.time()
    for i in range(configs.epoch):
        logger.info('epoch:{}/{}'.format(i + 1, configs.epoch))
        start_time = time.time()
        step, loss, loss_sum = 0, 0.0, 0.0
        for batch in tqdm(loader):
            sentences, _, attention_mask, entity_vec = batch
            sentences = sentences.to(device)
            attention_mask = attention_mask.to(device)
            entity_vec = entity_vec.to(device)
            model_output = model(sentences, attention_mask).to(device)
            loss = loss_function(model_output, entity_vec.float())
            loss = torch.sum(torch.mean(loss, 3), 2)
            loss = torch.sum(loss * attention_mask) / torch.sum(attention_mask)
            loss_sum += loss.item()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            step = step + 1

        model.eval()
        logger.info('start evaluate engines...')

        results_of_each_entity = predictor.evaluate(model, dev_data)

        time_span = (time.time() - start_time) / 60
        f1 = 0.0
        for class_id, performance in results_of_each_entity.items():
            f1 += performance['f1']
            # 打印每个类别的指标
            logger.info('class_name: %s, precision: %.4f, recall: %.4f, f1: %.4f'
                        % (class_id, performance['precision'], performance['recall'], performance['f1']))
        # 这里算得是所有类别的平均f1值
        f1 = f1 / len(results_of_each_entity)
        logger.info('time consumption:%.2f(min)' % time_span)

        if f1 >= best_f1:
            unprocessed = 0
            best_f1 = f1
            best_epoch = i + 1
            torch.save(model.state_dict(), os.path.join(configs.checkpoints_dir, 'best_model.pkl'))
            logger.info('saved model successful...')
        else:
            unprocessed += 1
        aver_loss = loss_sum / step
        logger.info(
            'aver_loss: %.4f, f1: %.4f, best_f1: %.4f, best_epoch: %d \n' % (aver_loss, f1, best_f1, best_epoch))
        if configs.is_early_stop:
            if unprocessed > configs.patient:
                logger.info('early stopped, no progress obtained within {} epochs'.format(configs.patient))
                logger.info('overall best f1 is {} at {} epoch'.format(best_f1, best_epoch))
                logger.info('total training time consumption: %.3f(min)' % ((time.time() - very_start_time) / 60))
                return
    logger.info('overall best f1 is {} at {} epoch'.format(best_f1, best_epoch))
    logger.info('total training time consumption: %.3f(min)' % ((time.time() - very_start_time) / 60))
