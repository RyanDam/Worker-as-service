#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Han Xiao <artex.xh@gmail.com> <https://hanxiao.github.io>
import os
import random
import sys
import time
import numpy as np
from .worker_skeleton import WKRWorkerSkeleton

class WKRHardWorker(WKRWorkerSkeleton):

    def __init__(self, id, args, worker_address_list, sink_address, device_id, name='WORKER', color='blue'):
        super().__init__(id, args, worker_address_list, sink_address, device_id, 
        args.gpu_memory_fraction, 
        args.model_name, 
        args.batch_size, 
        args.batch_group_timeout, 
        args.tmp_folder, 
        name=name, color=color)

    def get_env(self, device_id, tmp_dir):
        return []

    def get_model(self, envs, model_dir, model_name, tmp_dir):
        return []

    def get_preprocess(self, envs):
        def preprocessing(input):
            return input
        return preprocessing

    def get_postprocess(self, envs):
        def post_process(output):
            return output
        return post_process

    def predict(self, model, input):
        return input