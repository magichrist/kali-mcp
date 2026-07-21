"""Auto-import all tool modules to trigger registration."""

from tools.generic_command import GenericCommandTool
from tools.nmap import NmapTool
from tools.httpx import HttpxTool
from tools.nuclei import NucleiTool
from tools.ffuf import FfufTool
from tools.katana import KatanaTool
from tools.subfinder import SubfinderTool
from tools.amass import AmassTool
from tools.sqlmap import SqlmapTool
from tools.commix import CommixTool
from tools.wpscan import WpscanTool
from tools.enum4linux import Enum4linuxTool
from tools.netexec import NetexecTool
from tools.crackmapexec import CrackmapexecTool
from tools.bloodhound import BloodhoundTool
from tools.theharvester import TheharvesterTool
from tools.spiderfoot import SpiderfootTool
from tools.naabu import NaabuTool
from tools.arjun import ArjunTool
from tools.whatweb import WhatwebTool

ALL_TOOLS = [
    GenericCommandTool(),
    NmapTool(),
    HttpxTool(),
    NucleiTool(),
    FfufTool(),
    KatanaTool(),
    SubfinderTool(),
    AmassTool(),
    SqlmapTool(),
    CommixTool(),
    WpscanTool(),
    Enum4linuxTool(),
    NetexecTool(),
    CrackmapexecTool(),
    BloodhoundTool(),
    TheharvesterTool(),
    SpiderfootTool(),
    NaabuTool(),
    ArjunTool(),
    WhatwebTool(),
]
