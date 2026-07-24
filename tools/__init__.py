"""Auto-import all tool modules to trigger registration."""

from tools.generic_command import GenericCommandTool
from tools.python_command import PythonCommandTool
from tools.file_read import FileReadTool
from tools.file_write import FileWriteTool
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
from tools.dursgo import DursgoTool
from tools.zighound import ZighoundTool
from tools.searchsploit import SearchsploitTool
from tools.farsight import FarsightTool
from tools.flowlyt import FlowlytTool
from tools.zizmor import ZizmorTool
from tools.file_download import FileDownloadTool

ALL_TOOLS = [
    GenericCommandTool(),
    PythonCommandTool(),
    FileReadTool(),
    FileWriteTool(),
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
    DursgoTool(),
    ZighoundTool(),
    SearchsploitTool(),
    FarsightTool(),
    FlowlytTool(),
    ZizmorTool(),
    FileDownloadTool(),
]
