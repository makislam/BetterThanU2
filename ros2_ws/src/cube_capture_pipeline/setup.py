from glob import glob

from setuptools import find_packages, setup

package_name = "cube_capture_pipeline"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Makis",
    maintainer_email="makis@futurhandrobotics.com",
    description=(
        "One-call orchestration of cube_vision_tool's capture -> label -> "
        "compare -> solve scripts, so a full scan-to-solution pass doesn't "
        "need 5 hand-run commands."
    ),
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "pipeline_node = cube_capture_pipeline.pipeline_node:main",
        ],
    },
)
