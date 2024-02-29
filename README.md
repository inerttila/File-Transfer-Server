# File Transfer Server

File Transfer Server is a simple Flask-based web application for uploading files.

## Table of Contents

- [Introduction](#introduction)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)

## Introduction

File Transfer Server is a web application that allows users to upload files.

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

