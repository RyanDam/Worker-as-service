from wkr_serving.client import WKRClient, WKRWorker, WKRDecentralizeCentral
import time
import random
import numpy as np

class AIModel(WKRWorker):

    def get_model(self, ip, port, port_out):
        return WKRClient(ip=ip, port=port, port_out=port_out, check_version=False)

    def do_work(self, model, logger):
        try:
            start=time.time()
            audio = model.encode('Đoàn cũng sẽ kiểm tra tình hình sử dụng điện của một số khách hàng lớn tại từng khu vực, qua đó đánh giá mức độ ảnh hưởng của việc điều chỉnh giá điện tới chi phí mua điện và giá thành sản xuất kinh doanh của doanh nghiệp.')
            end=time.time()
            response_time = end-start
            duration = audio.shape[0]/16000
            logger.info('response time: {:.03f}\tresult: {}\tduration: {:.03f}'.format(response_time, audio.shape, duration))

            time.sleep(random.randint(1, 4))

        except Exception as e:
            logger.error('error: {}'.format(e))

    def off_model(self, model):
        model.close()

if __name__ == "__main__":
    from wkr_serving.client.helper import get_args_parser
    args = get_args_parser().parse_args(['-port', '12100',
                                        '-port_out', '12102',
                                        '-num_client', '5',
                                        '-remote_servers', '[["localhost", 8066, 8068]]',
                                        '-log_dir', '/data6/tts_service_log'])
    handler = WKRDecentralizeCentral(AIModel, args)
    handler.start()