from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="gittransfer",
    version="1.0.0",
    author="GitTransfer Tool",
    description="Transfer GitLab repositories to GitHub with complete history",
    long_description=long_description,
    long_description_content_type="text/markdown",
    py_modules=["gittransfer"],
    install_requires=requirements,
    python_requires=">=3.7",
    entry_points={
        "console_scripts": [
            "gittransfer=gittransfer:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Version Control",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)