"""Auto-import all tool modules to trigger registration.

The tool registry exposes the full inventory of tool wrappers so agents get
maximum capability. test_comprehensive.py's TOOL_ARGS map must include an
entry for every registered tool.
"""

from kmcp.tools.agent_interface import (
    AssessmentDiffTool,
    AssessmentRunTool,
    AssetGraphTool,
    BatchRunTool,
    CoverageSummaryTool,
    EvidenceGetTool,
    FindingsQueryTool,
    FindingTransitionTool,
    JobControlTool,
    ReportGenerateTool,
    ToolCatalogTool,
)
from kmcp.tools.amass import AmassTool
from kmcp.tools.arjun import ArjunTool
from kmcp.tools.bettercap import BettercapTool
from kmcp.tools.bloodhound import BloodhoundTool
from kmcp.tools.commix import CommixTool
from kmcp.tools.crackmapexec import CrackmapexecTool
from kmcp.tools.dirb import DirbTool
from kmcp.tools.dursgo import DursgoTool
from kmcp.tools.enum4linux import Enum4linuxTool

## Excluded: none — full tool inventory registered
from kmcp.tools.farsight import FarsightTool
from kmcp.tools.ffuf import FfufTool
from kmcp.tools.file_download import FileDownloadTool
from kmcp.tools.file_read import FileReadTool
from kmcp.tools.file_write import FileWriteTool
from kmcp.tools.flowlyt import FlowlytTool
from kmcp.tools.generic_command import GenericCommandTool
from kmcp.tools.gobuster import GobusterTool
from kmcp.tools.hashcat import HashcatTool
from kmcp.tools.help_tool import KmcpHelpTool
from kmcp.tools.httpx import HttpxTool
from kmcp.tools.hydra import HydraTool
from kmcp.tools.john import JohnTool
from kmcp.tools.katana import KatanaTool
from kmcp.tools.masscan import MasscanTool
from kmcp.tools.medusa import MedusaTool
from kmcp.tools.msfconsole import MsfconsoleTool
from kmcp.tools.naabu import NaabuTool
from kmcp.tools.netexec import NetexecTool
from kmcp.tools.nmap import NmapTool
from kmcp.tools.nuclei import NucleiTool
from kmcp.tools.parallel_execute import ParallelExecuteTool, ParallelStatusTool
from kmcp.tools.playbook_ad import PlaybookAdTool
from kmcp.tools.playbook_authoring import (
    PlaybookCreateTool,
    PlaybookPublishTool,
    PlaybookValidateTool,
)
from kmcp.tools.playbook_blackbox import (
    PlaybookCatalogTool,
    PlaybookResultTool,
    PlaybookRunTool,
)
from kmcp.tools.playbook_engine_tool import PlaybookEngineTool
from kmcp.tools.playbook_recon import PlaybookReconTool
from kmcp.tools.playbook_tools import PlaybookListTool, PlaybookStatusTool
from kmcp.tools.playbook_webapp import PlaybookWebappTool
from kmcp.tools.python_command import PythonCommandTool
from kmcp.tools.responder import ResponderTool
from kmcp.tools.searchsploit import SearchsploitTool
from kmcp.tools.spiderfoot import SpiderfootTool
from kmcp.tools.sqlmap import SqlmapTool
from kmcp.tools.subfinder import SubfinderTool
from kmcp.tools.template_tools import TemplateListTool, TemplateRunTool
from kmcp.tools.theharvester import TheharvesterTool
from kmcp.tools.vault_tool import (
    VaultDeleteTool,
    VaultListTool,
    VaultQueryTool,
    VaultReadTool,
    VaultStatsTool,
    VaultWriteTool,
)
from kmcp.tools.wfuzz import WfuzzTool
from kmcp.tools.whatweb import WhatwebTool
from kmcp.tools.wpscan import WpscanTool
from kmcp.tools.zap import ZapTool
from kmcp.tools.zighound import ZighoundTool
from kmcp.tools.zizmor import ZizmorTool

# Ordered list of tool instances (full inventory)
ALL_TOOLS = [
    KmcpHelpTool(),
    GenericCommandTool(),
    PythonCommandTool(),
    FileReadTool(),
    FileWriteTool(),
    FileDownloadTool(),
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
    FlowlytTool(),
    SearchsploitTool(),
    ZighoundTool(),
    ZizmorTool(),
    FarsightTool(),
    MsfconsoleTool(),
    HydraTool(),
    HashcatTool(),
    GobusterTool(),
    MasscanTool(),
    JohnTool(),
    ZapTool(),
    WfuzzTool(),
    DirbTool(),
    MedusaTool(),
    BettercapTool(),
    ResponderTool(),
    ParallelExecuteTool(),
    ParallelStatusTool(),
    PlaybookReconTool(),
    PlaybookWebappTool(),
    PlaybookAdTool(),
    PlaybookEngineTool(),
    PlaybookListTool(),
    PlaybookStatusTool(),
    VaultWriteTool(),
    VaultReadTool(),
    VaultQueryTool(),
    VaultListTool(),
    VaultDeleteTool(),
    VaultStatsTool(),
    FindingTransitionTool(),
    AssessmentDiffTool(),
    CoverageSummaryTool(),
    AssessmentRunTool(),
    BatchRunTool(),
    JobControlTool(),
    FindingsQueryTool(),
    EvidenceGetTool(),
    AssetGraphTool(),
    ToolCatalogTool(),
    ReportGenerateTool(),
    PlaybookRunTool(),
    PlaybookCatalogTool(),
    PlaybookResultTool(),
    PlaybookCreateTool(),
    PlaybookValidateTool(),
    PlaybookPublishTool(),
    TemplateListTool(),
    TemplateRunTool(),
]
