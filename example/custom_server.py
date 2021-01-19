import time
from wkr_serving.server import WKRServer, WKRHardWorker
from wkr_serving.server.helper import get_args_parser, import_tf

class Worker(WKRHardWorker):
    
    def get_env(self, device_id, tmp_dir):
        tf = import_tf(device_id=device_id)
        import numpy as np

        logger = self.new_logger()

        return [tf, np, logger]
    
    def get_model(self, envs, model_dir, model_name, tmp_dir):
        tf, np, logger = envs

        logger.info("Begin load model")
        try:
            # load model
            pass
        except Exception as e:
            logger.error("Load model error")

        return model, logger
    
    def predict(self, model, input):
        model, logger = model
        
        logger.info("Processing input: {}".format(input))

        start_process = time.time()
        # preprocess
        done_preprocess = time.time()
        # predict
        done_predict = time.time()

        logger.info("DONE input: {}".format(input))

        # log statistic number
        self.record_statistic({
            'preprocess': (done_preprocess-start_process)*1000/len(input),
            'predict': (done_predict-done_preprocess)*1000/len(input),
            'batchsize': len(input)
        })

        return result

if __name__ == "__main__":

    args = get_args_parser().parse_args([
        '-protocol', 'obj',
        '-model_dir', '/data1/ailabserver-models/face_service_models',
        '-model_name', 'mnet_double_10062019_tf19.pb',
        '-port_in', '8996',
        '-port_out', '8998',
        '-num_worker', '2',
        '-batch_size', '1',
        '-device_map', '-1',
        '-gpu_memory_fraction', '0.25'
    ])
    server = WKRServer(args, hardprocesser=Worker)

    # start server
    server.start()

    # join server
    server.join()
