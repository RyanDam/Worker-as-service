from os import path

from setuptools import setup, find_packages

# setup metainfo
libinfo_py = path.join('wkr_serving', 'server', '__init__.py')
libinfo_content = open(libinfo_py, 'r').readlines()
version_line = [l.strip() for l in libinfo_content if l.startswith('__version__')][0]
exec(version_line)  # produce __version__

setup(
    name='wkr_serving_server',
    version=__version__,
    description='distributed computing framework developed for the uses of Zalo/AILab',
    url='https://lab.zalo.ai',
    long_description=open('README.md', 'r').read(),
    long_description_content_type='text/markdown',
    author='duydv2',
    author_email='duydv2@vng.com.vn',
    license='MIT',
    packages=find_packages(),
    zip_safe=False,
    install_requires=[
        'numpy',
        'six',
        'pyzmq>=17.1.0',
        'GPUtil>=1.3.0',
        'termcolor>=1.1'
    ],
    extras_require={
        'cpu': ['tensorflow>=1.10.0'],
        'gpu': ['tensorflow-gpu>=1.10.0'],
        'http': ['flask', 'flask-compress', 'flask-cors', 'flask-json', 'bert-serving-client']
    },
    classifiers=(
        'Programming Language :: Python :: 3.6',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
    ),
    entry_points={
        'console_scripts': ['wkr-serving-start=wkr_serving.server.cli:main',
                            'wkr-serving-make=wkr_serving.server.cli:main_make',
                            'wkr-serving-terminate=wkr_serving.server.cli:terminate'],
    },
    keywords='tts nlp tensorflow machine learning sentence encoding embedding serving',
)
