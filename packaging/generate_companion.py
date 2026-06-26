import json
import copy

# This is the exact blueprint for a single button extracted from your template
BUTTON_TEMPLATE = {
    "type": "button",
    "style": {
        "text": "",
        "textExpression": False,
        "size": "auto",
        "png64": None,
        "alignment": "center:center",
        "pngalignment": "center:center",
        "color": 16777215,
        "bgcolor": 0,
        "show_topbar": "default"
    },
    "options": {
        "stepProgression": "auto",
        "stepExpression": "",
        "rotaryActions": False
    },
    "feedbacks": [],
    "steps": {
        "0": {
            "action_sets": {
                "down": [],
                "up": []
            },
            "options": {
                "runWhileHeld": []
            }
        }
    },
    "localVariables": []
}

def create_osc_action(path, value):
    """Creates a standard Companion OSC action object."""
    return {
        "action": "generic:osc",
        "options": {
            "host": "127.0.0.1",
            "port": 12000,
            "path": path,
            "args": [{"type": "i", "value": value}]
        }
    }

def generate_dialmouse_config():
    # Base structure
    config = {
        "version": 12,
        "type": "page",
        "companionBuild": "4.3.4+9244-stable-c14e5e3334",
        "page": {
            "id": "DialMouse_Generated_Page",
            "name": "DialMouse_Auto",
            "controls": {"0": {}}  # All buttons go here
        }
    }

    # Example: Populating button index "0"
    btn = copy.deepcopy(BUTTON_TEMPLATE)
    btn["style"]["text"] = "Start Dial"
    btn["steps"]["0"]["action_sets"]["down"].append(create_osc_action("/dialmouse/start", 1))
    
    config["page"]["controls"]["0"]["0"] = btn
    
    # Save to file
    with open("DialMouse_Layout.companionconfig", "w") as f:
        json.dump(config, f, indent=4)
    print("Successfully created DialMouse_Layout.companionconfig")

if __name__ == "__main__":
    generate_dialmouse_config()