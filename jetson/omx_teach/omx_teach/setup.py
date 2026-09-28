import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'omx_teach'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='jK',
    maintainer_email='wogus061@gmail.com',
    description='Kinesthetic teach and replay for the OMX-F arm.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'teach_node = omx_teach.teach_node:main',
            'teach = omx_teach.cli:main',
        ],
    },
)
