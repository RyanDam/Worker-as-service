from os import path

from setuptools import setup, find_packages

# setup metainfo
libinfo_py = path.join('wkr_serving', 'client', '__init__.py')
libinfo_content = open(libinfo_py, 'r').readlines()
version_line = [l.strip() for l in libinfo_content if l.startswith('__version__')][0]
exec(version_line)  # produce __version__

with open('requirements.txt') as f:
    require_packages = [line[:-1] if line[-1] == '\n' else line for line in f]

setup(
    name='wkr_serving_client',
    version=__version__,  # noqa
    description='Client interface for Worker-as-service',
    url='https://github.com/RyanDam/Worker-as-service',
    long_description=open('README.md', 'r').read(),
    long_description_content_type='text/markdown',
    author='Ryan Dam',
    author_email='py.ryan.dam@gmail.com',
    license='MIT',
    packages=find_packages(),
    zip_safe=False,
    install_requires=require_packages,
    entry_points={
        'console_scripts': ['wkr-decentral-switch=wkr_serving.client.cli:switch_remote_server',
                            'wkr-decentral-status=wkr_serving.client.cli:show_config',
                            'wkr-decentral-terminate=wkr_serving.client.cli:terminate',
                            'wkr-decentral-idle=wkr_serving.client.cli:idle',
                            'wkr-decentral-restart=wkr_serving.client.cli:restart_clients'],
    },
    classifiers=(
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.6',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
    ),
    keywords='pytorch nlp tensorflow machine learning sentence encoding embedding serving',
)
