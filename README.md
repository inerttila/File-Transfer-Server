# File Transfer Server

File Transfer Server is a simple Flask-based web application for uploading files.

## Table of Contents

- [Introduction](#introduction)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Features](#features)
- [Contributing](#contributing)
- [Contact](#Contact)

## Introduction

File Transfer Server is a web application that allows users to upload files. This README provides information on how to set up and use the application.

## Prerequisites

Before you begin, ensure you have met the following requirements:

- Python (>=3.6)
- Flask (>=1.0)
- Other dependencies (see [requirements.txt](requirements.txt))

## Installation

1. Clone the repository:

```shell
git clone https://github.com/inerttila/File-Transfer-Server.git
```

### Install dependencies:

```shell
pip install -r requirements.txt

```
## Configuration
Before running the server, you may need to configure the IP address in the server.py code. Follow these steps to set your IP address:

Open the server.py file in a text editor.

Locate the following line of code:
```shell
app.run(host="your_ip_address_here", port="80")
```
## Usage
To run the application, execute the following command:

```shell
python server.py

```

This will start the server, and you can access it in your web browser at
http://localhost:5000.

## Features
File upload functionality

## Contributing
Contributions are welcome! Here's how you can contribute:

Fork the project.
Create a new branch 
```shell
git checkout -b feature/YourFeature
```
Commit your changes
```shell
git commit -m 'Add some feature'
```
Push to the branch
```shell
git push origin feature/YourFeature
```
Open a pull request.

Please follow our coding standards and conventions.

You can copy this template and replace https://github.com/inerttila/File-Transfer-Server.git with the actual URL of your Git repository. Additionally, you should fill in the sections with relevant content specific to your project.

## Contact

For inquiries or assistance, feel free to reach out through the following channels:

- Email: [inert.etila@gmail.com](mailto:inert.etila@gmail.com)
- LinkedIn: [Inert Tila](https://al.linkedin.com/in/inerttila)

You can email me for any questions or support related to this project, and you can also connect with me on LinkedIn to stay updated on my professional activities.
