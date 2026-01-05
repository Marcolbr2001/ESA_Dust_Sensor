<div align="center">
<!--
[![GitHub last commit](https://img.shields.io/github/last-commit/Marcolbr2001/Dust_Sensor?style=for-the-badge)](https://github.com/Marcolbr2001/Dust_Sensor/commits/main)
[![Issues](https://img.shields.io/github/issues/Marcolbr2001/Dust_Sensor?style=for-the-badge)](https://github.com/Marcolbr2001/Dust_Sensor/issues)
[![MIT License](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
-->
</div>

<br />
<div align="center">

  <h2 align="center">Dust Sensor System</h2>

  <p align="center">
    Fully electronic system for real-time tracking of dust particle deposition in space applications    <br />
    <a href="https://github.com/Marcolbr2001/Dust_Sensor"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/Marcolbr2001/Dust_Sensor">View Repo</a>
    ·
    <a href="https://github.com/Marcolbr2001/Dust_Sensor/issues">Report Bug</a>
    ·
    <a href="https://github.com/Marcolbr2001/Dust_Sensor/issues">Request Feature</a>
  </p>
</div>

<div align="center">
  <a href="https://github.com/Marcolbr2001/Dust_Sensor">
    <img src="https://github.com/user-attachments/assets/70fec228-3cf5-4fef-bc37-bc2c930fc334" alt="Logo" heigth="400" width="400">
  </a>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>


## About The Project

<!--[![Product Screenshot][product-screenshot]](https://github.com/Marcolbr2001/Dust_Sensor)-->

This work presents the development of a system designed to support dust sensor integration, with specific attention to EMC, power, and dimensional constraints. For the final user, they only need to connect via Bluetooth the board and work with the computer interface, monitoring correctly the environment.

Here are some of the key steps to a correct utilization of the system:
* Placing the carrier board carefully into the motherboard
* Open the GUI and connect the board
* Monitoring dust status

> [!NOTE]
> This tutorial addresses all the steps and potential issues you may encounter during your setup. It is not intended to cover all the PCB, firmware and software technical implementation. If you are interested, please contact me.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Description of Archive

<pre>
├─ src                     # This folder contains all the files to build the project
   └─ GUI                  # The user interface to communicate with the sensor
   └─ PCBs                 # PCBs file and guide to boards hardware
   └─ firmware             # Current last-version firmware uploaded in the microcontroller
├─ README.md               # This file
└─ project_overview.pdf    # pdf overview, sensors's theoretical foundation and board functionality

</pre>

### Built With

This section lists the major frameworks/libraries used to bootstrap your project.

[![C](https://img.shields.io/badge/C-00599C?style=for-the-badge&logo=c&logoColor=white)](https://en.wikipedia.org/wiki/C_(programming_language))
<br>
[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
<br>
[![Altium Designer](https://img.shields.io/badge/Altium_Designer-A5915F?style=for-the-badge&logo=altiumdesigner&logoColor=white)](https://www.altium.com/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>


## Getting Started

This is an example of how you may give instructions on setting up your project locally. To get a local copy up and running follow these simple example steps.

### Setting up the GUI

In order to have all the files into your local computer, open a folder in which you want to download the project and open a new terminal in that folder.

1.  Clone the repo
    ```sh
    git clone [https://github.com/](https://github.com/)Marcolbr2001/Dust_Sensor.git .
    ```
Now we can start by using our sensor to do measurements. 

2. To use the software you have to navigate into ``` src/GUI ```, and simply run the file named ```DUST_Monitor.exe```

> [!WARNING]
> Your antivirus may block the executable. You might need to grant permission to run the file.

 If you are not able to run the program, you can launch it directly within Python. If you did not encounter this problem, you can go directly to point 6.

3.  Navigate into the folder
    ```sh
    src/GUI/src
    ```
4.  Install dependencies
    ```sh
    pip install -r requirements.txt
    ```
5.  In case you do not have Python in your computer run this command
    ```sh
    winget install -e --id Python.Python.3.11; Start-Process powershell -Verb RunAs -ArgumentList "-NoExit -Command pip install customtkinter pillow bleak pyserial"
    ```

A page like that will be showed to you.
<div align="center">
  <a href="https://github.com/Marcolbr2001/Dust_Sensor">
<img width="400" height="300" alt="dustGUI_first_page" src="https://github.com/user-attachments/assets/7469d1cf-9a90-492e-b1e8-32f5d7a810ce" />
  </a>
</div>
<p align="right">(<a href="#readme-top">back to top</a>)</p>


## Usage

Use this space to show useful examples of how a project can be used. Additional screenshots, code examples and demos work well in this section.

![Usage Example](images/example-usage.gif)

*Example command:*
```sh
python main.py --help
