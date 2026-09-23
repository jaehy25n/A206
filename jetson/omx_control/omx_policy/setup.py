from setuptools import find_packages, setup

package_name = 'omx_policy'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='J',
    maintainer_email='wogus061@gmail.com',
    description='Policy node interface and scripted dummy policy for the OMX stack.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'dummy_policy_node = omx_policy.dummy_policy_node:main',
        ],
    },
)
