import os
from glob import glob

from setuptools import find_packages, setup

package_name = "cube_solver"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Makis",
    maintainer_email="makis@futurhandrobotics.com",
    description=(
        "Pluggable cube-solving backends (Kociemba now, others later) that turn a "
        "facelet state into moves and drive them through the motor rig."
    ),
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "cube_solver_node = cube_solver.solver_node:main",
        ],
    },
)
