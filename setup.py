from setuptools import setup

import spoqify


with open('README.md') as f:
    long_description = f.read()

setup(
    name='spoqify',
    version=spoqify.__version__,
    author='Jakob de Maeyer',
    author_email='jakob@naboa.de',
    description="Spotify playlist anonymizer",
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://spoqify.com/',
    project_urls={
        'Source': 'https://github.com/jdemaeyer/spoqify/',
        'Tracker': 'https://github.com/jdemaeyer/spoqify/issues/',
    },
    packages=['spoqify'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        'aiohttp',
        'quart',
    ],
)
