#!/usr/bin/env python
# coding=utf-8


from setuptools import setup
from dnsmanager import __version__

setup(
    name='dns-manager',
    version=__version__,
    author='fangwentong',
    author_email='fangwentong2012@gmail.com',
    license='MIT',
    packages=['dnsmanager'],
    package_dir={'dnsmanager': 'dnsmanager'},
    zip_safe=False,
    include_package_data=True,
    entry_points={
        'console_scripts': ['dns-manager=dnsmanager.dns_cli:main']
    },
    install_requires=['PyNamecheap==0.0.3', 'aliyun-python-sdk-alidns==2.0.6', 'cloudflare==2.8.15', 'PyYAML==5.4']
)
