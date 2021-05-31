import time
from wkr_serving.server import WKRServer, WKRHardWorker
from wkr_serving.server.helper import get_args_parser

from fastapi import File, Form
from typing import Optional

from wkr_serving.server.http import download_img_file, convert_bytes_to_pil_image

# HOW IT WORK?
# Step 1: define 'api_appender' function
# Step 2: add '-http_new' to args
# Step 3: pass 'api_appender' to 'http_api_appender' param of WKRServer

# STEP 1
def api_appender(app, bc):
    # Define http endpoint for server
    #   app: FastAPI application, for more instruction: https://fastapi.tiangolo.com/tutorial/first-steps/
    #   bc: worker-as-service client
    # Some example:

    # predict image from url
    # example call:
    # curl --location --request POST 'http://0.0.0.0:9000/predict_url' --form 'image_url="some_url"'
    @app.post('/predict_url')
    def predict_url(
        image_url: str = Form(...)
    ):
        try:
            image = download_img_file(image_url)
            result = bc.encode(image)
            return {
                "error_code": 0,
                "error_message": "Successful.",
                "data": result
            }
        except Exception as e:
            return {
                "error_code": 1,
                "error_message": "Internal error",
                "data": {}
            }

    # predict image file uploaded from client, with 2 custom parameter
    # example call:
    # curl --location --request POST 'http://0.0.0.0:9000/predict_img_file' --form 'img_byte=@"path/to/img.jpg"'
    # curl --location --request POST 'http://0.0.0.0:9000/predict_img_file' --form 'img_byte=@"path/to/img.jpg"' --form 'option1="2"'
    # curl --location --request POST 'http://0.0.0.0:9000/predict_img_file' --form 'img_byte=@"path/to/img.jpg"' --form 'option2="1"'
    @app.post('/predict_img_file')
    def predict_url(
        img_byte: bytes = File(...),
        option1: Optional[int] = 0,
        option2: Optional[int] = 1,
    ):
        try:
            image = convert_bytes_to_pil_image(img_byte)
            result = bc.encode(image)
            return {
                "error_code": 0,
                "error_message": "Successful.",
                "data": result
            }
        except Exception as e:
            return {
                "error_code": 1,
                "error_message": "Internal error",
                "data": {}
            }

    # normalize text input
    # example call:
    # curl --location --request POST 'http://0.0.0.0:9000/normalize' --form 'text="this is a very long paragraph"'
    @app.post('/normalize')
    def normalize(
        text: str = Form(...)
    ):
        try:
            normalized = bc.encode(text)
            return {
                "error_code": 0,
                "error_message": "Successful.",
                "data": normalized
            }
        except Exception as e:
            return {
                "error_code": 1,
                "error_message": "Internal error",
                "data": {}
            }

class Worker(WKRHardWorker):
    
    def get_env(self, device_id, tmp_dir):
        return []
    
    def get_model(self, envs, model_dir, model_name, tmp_dir):
        return []
    
    def predict(self, model, input):
        return [{"age": "19"}]

if __name__ == "__main__":

    args = get_args_parser().parse_args([
        '-protocol', 'obj',
        '-model_dir', '/data1/ailabserver-models/face_service_models',
        '-model_name', 'mnet_double_10062019_tf19.pb',
        '-port_in', '9001',
        '-port_out', '9002',
        '-http_port', '9000',
        '-num_worker', '1',
        '-batch_size', '1',
        '-device_map', '-1',
        '-http_max_connect', '20',
        '-gpu_memory_fraction', '0.25',
        '-http_new' # STEP 2
    ])

    # STEP 3
    server = WKRServer(args, hardprocesser=Worker, http_api_appender=api_appender)

    # start server
    server.start()

    # join server
    server.join()
