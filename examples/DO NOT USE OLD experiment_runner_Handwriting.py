import os
import time
import datetime
import socket
import logging
import threading
import json
from pylsl import StreamInfo, StreamOutlet  
import queue
import tkinter as tk
from tkinter import ttk

use_ui = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
# Experiment Configuration
experiment_name = "HandWriting_Pilot".replace(" ", "_")
conducted_time = datetime.datetime.now()
subject_id = 1
trial_number = 1

comment = ""

class ExperimentUI:
    def __init__(self, root: tk.Tk, ui_queue: queue.Queue):
        self.root = root
        self.ui_queue = ui_queue

        self.root.title("Experiment Blocks")
        self.root.geometry("520x360")

        container = ttk.Frame(root, padding=12)
        container.pack(fill="both", expand=True)

        self.title_lbl = ttk.Label(container, text="Current Block", font=("Segoe UI", 12, "bold"))
        self.title_lbl.pack(anchor="w")

        self.block_var = tk.StringVar(value="—")
        self.block_lbl = ttk.Label(container, textvariable=self.block_var, font=("Segoe UI", 20, "bold"))
        self.block_lbl.pack(anchor="w", pady=(0, 8))

        self.word_title = ttk.Label(container, text="Resolved Word", font=("Segoe UI", 12, "bold"))
        self.word_title.pack(anchor="w")

        self.word_var = tk.StringVar(value="—")
        self.word_lbl = ttk.Label(container, textvariable=self.word_var, font=("Segoe UI", 16))
        self.word_lbl.pack(anchor="w", pady=(0, 12))

        ttk.Separator(container, orient="horizontal").pack(fill="x", pady=8)

        self.map_title = ttk.Label(container, text="Word Mapping", font=("Segoe UI", 12, "bold"))
        self.map_title.pack(anchor="w")

        self.map_list = tk.Listbox(container, height=6)
        self.map_list.pack(fill="both", expand=True)

        self._populate_mapping()
        self._poll_queue()

    def _populate_mapping(self):
        self.map_list.delete(0, "end")
        # Build lines like: "Word1 → apple"
        for i, w in enumerate(display_words, start=1):
            self.map_list.insert("end", f"Word{i} \\u2192 {w}")

    def _poll_queue(self):
        # Process messages from the worker thread
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                if msg[0] == "block":
                    block_name = msg[1]
                    self.block_var.set(block_name)
                    resolved = resolve_word(block_name)
                    self.word_var.set(resolved if resolved else "—")
                elif msg[0] == "refresh_map":
                    self._populate_mapping()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

ui_queue = queue.Queue()


# Incoming messages from the UR3 are compared to the markers table,
# if the messgae is found the ID is sent as a marker
# If we're using ur3, how is the block design ran?
# Using the UR3 we cannot rely on the accurate timings in this script,
# meaning the block design should be passive
blockless = False

# Block Design
blocks = [ "Rest", "Word1", "Word2", "Word3"]
durations = [ 20, 10, 10, 10 ] # Seconds
block_order = [0, 1, 0, 2, 3,
               0, 1, 0, 2, 3,
               0, 1, 0, 2, 3,
               0
               ] # NOTE : This are indices into the Blocks array
wait_for_input_blocks = [ False, False, False, False ] # If True : to proceed to next block, a manual input is needed

# Baseline Configuration
baseline_duration = 30 # 30s pre and post baselines
use_baseline = False

display_words = ["HELLO", "BANANA", "WRITING"]

def resolve_word(block_name: str) -> str:
    if block_name.startswith("Word"):
        try:
            idx = int(block_name[4:]) - 1
            if 0 <= idx < len(display_words):
                return display_words[idx]
        except ValueError:
            pass
    return ""


# NOTE : We need to test wheter or not g.Recorder can handle values above 9
markers = {
        "Rest" : 0,
        "Word1" : 1,
        "Word2" : 2,
        "Word3" : 3,
}

use_fnirs   = True # Send Markers to aurora
use_eeg     = False # Send Markers to gRecorder

def validate_block_design(): # NOTE : This verifies your block design is possible to complete
    assert(len(durations) == len(blocks)) # Each block needs a duration
    for block_idx in block_order: 
        assert(block_idx >= 0) # The block index must be inside the bounds of the Blocks array,
        assert(block_idx < len(blocks)) # 0 < idx < len(Blocks)
    assert(len(wait_for_input_blocks) == len(blocks)) # Each block must either manually or automatically proceed
validate_block_design()

def print_experiment_description():
    print(f"Welcome To Experiment : {experiment_name}")
    print(f"Conducted : {conducted_time.ctime()}")
    print(f"Subject ID : {subject_id}")
    print(f"Trial : {trial_number}")
    order_string = ""
    for elm in block_order:
        order_string = order_string + (blocks[elm] + "->")
    order_string = order_string + "End"
    print("Block Order : ", order_string)
print_experiment_description()  

def save_experiment_to_file():
    encoded = {
        "experiment_name": experiment_name, # Experiment
        "date_time": conducted_time.strftime("%d_%m_%Y_%H_%M_%S"),
        "subject_ID": subject_id,
        "trial_number" : trial_number, 
        
        "blocks" : blocks, # Block Design
        "durations" : durations,
        "block_order" : block_order,
        "block_wait_for_input" : wait_for_input_blocks,
        
        "markers" : markers,

        "using_fnirs" : use_fnirs,
        "using_eeg" : use_eeg,
        #"use_ur3" : use_ur3, this is the robot, which we do not posess
    }
    filename = experiment_name + "_" + conducted_time.strftime("%d_%m_%Y_%H_%M_%S") + "subject_" + str(subject_id) +  "_trial_" + str(trial_number) + ".json"
    filepath = os.path.join(LOG_DIR, filename)

    with open(filepath, "w") as json_file:
        json.dump(encoded, json_file, indent=4)
    json_file.close()
save_experiment_to_file()

def setup_logging(): # NOTE : Use logging.debug|info|error|warning to write to screen and console, use printf for only console
    log_filename = experiment_name + "_" + conducted_time.strftime("%d_%m_%Y_%H_%M_%S") + "subject_" + str(subject_id) + "_trial_" + str(trial_number) + ".log"
    log_filepath = os.path.join(LOG_DIR, log_filename)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_filepath), logging.StreamHandler()],
    )
    logging.getLogger().handlers[0].level = logging.DEBUG
    logging.getLogger().handlers[1].level = logging.INFO # Dont print debug info to console
setup_logging()

# EEG 
# g.Recorder listens to a socket via the Universal Datagram Protocol (UDP)
eeg_target_ip = '127.0.0.1'  # Change this to g.Recorder computer IP address | 127.0.0.1 for localhost
eeg_target_port = 1000  # Change this to the port set in g.Recorder
eeg_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # IPv4 UDP Socket 
logging.info(f"g.Recorder : UDP socket established {eeg_target_ip} : {eeg_target_port}")

def fill_grecorder_xml_msg(input): #inser input into XML as required by g.Recorder
    msg = '<gRecorder><DAQ.KeyboardMarkerUdpMessage assembly="gRecorder" name="' + str(input) + '"/></gRecorder>'
    return msg

# fNIRS
# Aurora is listening to a Lab Streaming Layer (LSL) named "Trigger" of type "Markers"
stream_name = "Trigger"
stream_type = "Markers"
stream_channels = 1
stream_format = "int32"
stream_id = "ADEPT"
fnirs_info = StreamInfo(name=stream_name, 
                        type=stream_type, 
                        channel_count=stream_channels, 
                        channel_format=stream_format, 
                        source_id=stream_id) 
fnirs_outlet = StreamOutlet(fnirs_info) # LSL outlet
logging.info(f"LSL outlet established {stream_name}:{stream_type}, {stream_channels}x{stream_format} @ {stream_id}")

def push_marker(marker:int):
    if use_fnirs:
        fnirs_outlet.push_sample([marker]) 
    if use_eeg: # NOTE : This is already encoded to bytes
        xml_msg = fill_grecorder_xml_msg(marker)
        eeg_socket.sendto(xml_msg.encode(), (eeg_target_ip, eeg_target_port)) 
    logging.debug("Pushed marker : " + str(marker))

    
def block_order_with_active_border(active_idx):
    order = ""
    for idx in range(len(block_order)):
        block = blocks[block_order[idx]]
        if idx == active_idx:
            order += "[" + block.upper() + "]" + "->"
        else:
            order += block + "->"

        if idx == len(block_order) - 1:
            order += "END"
    return order

def run_block_design():
    for idx, block in enumerate(block_order):
        
        block_onset = time.time() # When did the block start?
        current_block = blocks[block] # Name of the current block
        block_duration = durations[block] # How long does this block last
        is_final_block = (idx == (len(block_order) - 1)) # Is this the final block?

        logging.info(f"Started Block : [{current_block}]") # Log the onset of this block
        
        print(f"\\nStarted Block : [{current_block}]")
        print(f"Order : {block_order_with_active_border(idx)}")

        if use_ui:
            try:
                ui_queue.put(("block", current_block))
            except Exception:
                pass

        
        push_marker(block) # Mark data what block started
    
        if wait_for_input_blocks[block]: #Handle manual procedure blocks
            if is_final_block: # Is this the final block?
                proceed = input(F"Current Block : [{current_block}] | Press [ ENTER ] to complete trial...")
            else:
                proceed = input(f"Current Block : [{current_block}] | Press [ ENTER ] to proceed to next block : [{blocks[block_order[idx + 1]]}]")
            continue

        while True:
            elapsed_time = time.time() - block_onset
            remaining_time = block_duration - elapsed_time

            if remaining_time <= 0:
                break
            
            if not is_final_block: 
                print(f"Current Block : [{current_block}] | Starting [{blocks[block_order[idx + 1]]}] in {remaining_time:.2f} seconds...", end="\\r")
            else: 
                print(f"Current Block : [{current_block}] | Remaining time : {remaining_time:.2f} seconds...", end='\\r')


            time.sleep(0.1)  # Sleep to prevent excessive CPU usage
    print()
    logging.info(f"Completed Block : [{current_block}]")
    #print(f"Completed Block : [{current_block}]")

# BASELINES RECORDING
def record_pre_trial_baseline():
    logging.info(f"Started Pre-block design baseline : {baseline_duration} seconds")
    push_marker(markers["Start"])
    start_time = time.time()
    while True:
        elapsed_time = time.time() - start_time
        remaining_time = baseline_duration - elapsed_time

        if remaining_time <= 0:
            break
        
        print(f"Baseline : Remaining time : {remaining_time:.2f} seconds...", end='\\r')
        time.sleep(0.1)
    
    logging.info(f"Completed Pre-block design baseline : {baseline_duration} seconds")
    
def record_post_trial_baseline():
    start_time = time.time()
    logging.info(f"Started Post-block design baseline : {baseline_duration} seconds")
    while True:
        elapsed_time = time.time() - start_time
        remaining_time = baseline_duration - elapsed_time

        if remaining_time <= 0:
            break
        
        print(f"Baseline : Remaining time : {remaining_time:.2f} seconds...", end='\\r')
        time.sleep(0.1)
    push_marker(markers["End"])
    logging.info(f"Completed Post-block design baseline : {baseline_duration} seconds")
                    

#if use_baseline:
#    ready = input(f"Press [ ENTER ] to start {baseline_duration} second baseline recording")
#    record_pre_trial_baseline()
#
# # CONDUCT BLOCK DESIGN
#if not blockless:
#    run_block_design()
#    
#if blockless:
#    while True:
#        # How do we run blockless ? 
#        # This just sits waiting for UR3 robot messages, or manual entry
#        
#        for marker_name, marker_value in markers.items():
#           print(f" [ {marker_name} ] : {marker_value}")
#        # print options
#        # N = Complete block design and start post-block baseline
#        print(f" [ N ] : Complete block design and start {baseline_duration} second baseline recording")
#        ans = input("Command : ")
#        
#        if ans.upper() == "N":
#            break
#
#        push_marker(int(ans))
#if use_baseline:
#    record_post_trial_baseline()
    
def _experiment_entrypoint():
    # keep your existing flow here
    if use_baseline:
        ready = input(f"Press [ ENTER ] to start {baseline_duration} second baseline recording")
        record_pre_trial_baseline()

    if not blockless:
        run_block_design()
    else:
        while True:
            for marker_name, marker_value in markers.items():
               print(f" [ {marker_name} ] : {marker_value}")
            print(f" [ N ] : Complete block design and start {baseline_duration} second baseline recording")
            ans = input("Command : ")
            if ans.upper() == "N":
                break
            try:
                push_marker(int(ans))
            except ValueError:
                logging.warning(f"Invalid input (not an int): {ans}")

    if use_baseline:
        record_post_trial_baseline()

    logging.info("Experiment Complete.")

if use_ui:
    # Tk in main thread, experiment in worker thread
    root = tk.Tk()
    ui = ExperimentUI(root, ui_queue)

    worker = threading.Thread(target=_experiment_entrypoint, daemon=True)
    worker.start()

    root.mainloop()
else:
    # No UI → run in current thread as before
    _experiment_entrypoint()

exit()


#logging.info("Experiment Complete.")
#exit() # Threads should close automatically
