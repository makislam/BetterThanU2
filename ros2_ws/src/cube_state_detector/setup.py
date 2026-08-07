import os
from glob import glob

from setuptools import find_packages, setup

package_name = "cube_state_detector"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Makis",
    maintainer_email="makis@futurhandrobotics.com",
    description="Reads the full state of a Rubik's Cube using two fixed RealSense D405 cameras.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "cube_state_node = cube_state_detector.cube_state_node:main",
        ],
    },
)
