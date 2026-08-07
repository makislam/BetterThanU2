import os
from glob import glob

from setuptools import find_packages, setup

package_name = "cube_motor_control"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Makis",
    maintainer_email="makis@futurhandrobotics.com",
    description="Keyboard teleop for the Rubik's Cube rig's 6 Dynamixel face motors.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "keyboard_motor_control = cube_motor_control.keyboard_motor_control:main",
        ],
    },
)
