# v2 workflow directory

This folder contains the active ComfyUI Export(API) workflows used by DOBEDUB STUDIO.

The current active set is:

- `1-images.json`
- `Blowbang1.json`
- `Pickme_Workflow.json`
- `video_minimax_h3_r2v.json`
- `video_wan2_2_14B_flf2v_2-images-1.json`

Each workflow must have a matching `*.paramconfig.json` file. The paramconfig files map UI controls to the exact node IDs and input fields in the active workflow JSON.

The v2 workflows already include final and segment `SaveVideo` nodes. The server uses those existing nodes and does not add dynamic `SaveVideo` nodes at runtime.
