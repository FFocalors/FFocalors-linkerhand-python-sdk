import os
path = os.path.join(os.path.dirname(__file__), "..", "..", "example", "gui_control", "lhgui", "widgets", "hand_pose_view.py")
path = os.path.normpath(path)
print(f"Target: {path}")
print(f"Exists: {os.path.isfile(path)}")
