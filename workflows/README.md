# v2 workflow directory

This folder is the runtime compatibility view for ComfyUI Export(API)
workflows used by DOBEDUB STUDIO. Workflow approval is not defined by a
filename list. Definitions, immutable revisions, and active status are stored
in the database and managed only from Admin > Workflow Definitions.

Activating a validated revision promotes its workflow and paramconfig files to
this directory. Deactivation does not delete either the immutable release or
the compatibility files, so in-flight and historical records remain readable.

Each workflow must have a matching `*.paramconfig.json` file. The paramconfig files map UI controls to the exact node IDs and input fields in the active workflow JSON.

The server uses the nodes present in each registered workflow and does not add
dynamic `SaveVideo` nodes at runtime.
