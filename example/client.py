import numpy as np
from wkr_serving.client import WKRClient

if __name__ == "__main__":
    client = WKRClient(ip='0.0.0.0', port=8996, port_out=8998, check_version=False)
    input = np.zeros((5,5))
    output = client.encode(input)