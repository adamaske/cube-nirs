
import os
import time
import datetime
import socket
import logging
import threading
import json
from pylsl import StreamInfo, StreamOutlet  

# Experiment
experiment_name = "Harron Hybrid Finger Tapping".replace(" ", "_")
conducted_time = datetime.datetime.now()
subject_id = 0
trial_number = 3
comments = ""

markers = {
    "REST block started" : 0,
    "STIMULI block staarted" : 1,
    "waypoint 2 reached" : 13,
    "reset system" : 99,
}

# Block Design
blocks = [ "Rest", "Right", "Left" ]
durations = [ 20, 10, 10 ] # Seconds
block_order = [ 0, 1, 0, 2, 
               0, 1, 0, 2, 
               0, 1, 0, 2, 
               0] # NOTE : This are indices into the Blocks array
wait_for_input_blocks = [ False, False, False ] # If True : to proceed to next block, a manual input is needed

use_fnirs   = True # Send Markers to aurora
use_eeg     = True # Send Markers to gRecorder
use_ur3     = False # NOTE : This requires the program to wait for an accepted connection before experiment can start

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
        "use_ur3" : use_ur3,
    }
    filename = experiment_name + "_" + conducted_time.strftime("%d_%m_%Y_%H_%M_%S") + "subject_" + str(subject_id) +  "_trial_" + str(trial_number) + ".json"
    filepath = "logs/" + filename 

    with open(filepath, "w") as json_file:
        json.dump(encoded, json_file, indent=4)
    json_file.close()
save_experiment_to_file()

# Logging
# NOTE : Use logging.debug|info|error|warning to write to screen and console, use printf for only console
log_filename = experiment_name + "_" + conducted_time.strftime("%d_%m_%Y_%H_%M_%S") + "subject_" + str(subject_id) + "_trial_" + str(trial_number) + ".log"
log_filepath = "logs/" + log_filename
logging.basicConfig(
    level=logging.DEBUG,  # Set the lowest level to capture all messages
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filepath),  # Log to a text file
        logging.StreamHandler()  # Log to the console
    ]
)
logging.getLogger().handlers[0].level = logging.DEBUG
logging.getLogger().handlers[1].level = logging.INFO # Dont print debug info to console

# EEG 
# g.Recorder listens to a socket via the Universal Datagram Protocol (UDP)
eeg_target_ip = '127.0.0.1'  # Change this to g.Recorder computer IP address
eeg_target_port = 1000  # Change this to the port set in g.Recorder
eeg_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # IPv4 UDP Socket 
logging.info(f"UDP socket established {eeg_target_ip} : {eeg_target_port}")

def fill_grecorder_xml_msg(input): #inser input into XML as required by g.Recorder
    msg = '<gRecorder><DAQ.KeyboardMarkerUdpMessage assembly="gRecorder" name="' + str(input) + '"/></gRecorder>'
    return msg.encode()

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

# UR3 Connection - TCP Server
ur_server_ip = "127.0.0.1" # use "ipconfig"  to get this server
ur_server_port = 32000 #
# NOTE : This ip, and port must be set in the UR3 program "Before Start" module -> socket_open(ip, port)
ur_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP server
ur_server.bind((ur_server_ip, ur_server_port))
ur_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # NOTE : Dont use, reserved for connection
logging.info(f"TCP server established on {ur_server_ip} : {ur_server_port}")

if use_ur3: 
    print(f"Please establish the UR3 TCP connection before starting experiment : ")
    ur_server.listen(1)
    print(f"TCP server listening on {ur_server_ip}:{ur_server_port} and waiting for UR3 connection...")
    ur_socket, ur_address = ur_server.accept()
    logging.info(f"Connection established with UR3 : {ur_address}.")

# UR3 Force Sensor
pressure_readings = []
pressure_timings = []
pressure_threshold = 50
def handle_incoming_pressure_reading(pressure:int):
    pressure_readings.append(pressure)
    pass
    
def push_marker(marker:int):
    if use_fnirs:
        fnirs_outlet.push_sample([marker])
    if use_eeg:
        eeg_socket.sendto(fill_grecorder_xml_msg(marker), (eeg_target_ip, eeg_target_port)) # NOTE : This is already encoded to bytes
    if use_ur3:
       # the robot doesnt receieve any markers
       pass

    logging.debug("Pushed marker : " + str(marker))

def push_block_onset_marker(block_idx:int): # Marks data with the onset of each block.
    if use_fnirs:
        fnirs_outlet.push_sample([block_idx])
    if use_eeg:
        eeg_socket.sendto(fill_grecorder_xml_msg(block_idx), (eeg_target_ip, eeg_target_port)) # NOTE : This is already encoded to bytes
    if use_ur3:
       pass
    logging.debug("Pushed marker : " + str(block_idx))


print_experiment_description()  

start = input(f"Press [ ENTER ] to start first trial block [{blocks[block_order[0]]}]...")
experiment_running = True

if use_ur3:
    def decode_ur_message(data):
        if len(data) == int.__sizeof__(): #Check if we receive an integer, then its a pressure reading
            handle_incoming_pressure_reading(int.from_bytes(data, "big"))
            return None
        try:
            decoded_data = data.decode("utf-8").strip()  # Decode bytes to string
            return decoded_data  # Otherwise, return as string
        except UnicodeDecodeError:
            logging.error(f"UR3 Server : Recieved undecodable data -> {data}")

    def run_ur_server():
        while experiment_running:
            data = ur_socket.recv(1024)  # Receive up to 1024 bytes
            msg = decode_ur_message(data)
            
            key = markers[msg]
            if key is not None:
                push_marker(key)

    ur_server_thread = threading.Thread(target=run_ur_server)
    ur_server_thread.start()
    ur_socket.send("PROGRAM STARTED")


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


for idx in range(len(block_order)):
    block_start_time = time.time()
    block_idx = block_order[idx]
    current_block = blocks[block_idx]
    block_duration = durations[block_idx]
    is_final_block = (idx == (len(block_order) - 1)) 

    logging.info(f"Started Block : [{current_block}]") # Notify controller 
    print(f"\nStarted Block : [{current_block}]")
    print(f"Order : {block_order_with_active_border(idx)}")
    push_block_onset_marker(block_idx) # Mark data what block started
    
    
    if wait_for_input_blocks[block_idx]: #Handle manual procedure blocks
        if is_final_block: # Is this the final block?
            proceed = input(F"Current Block : [{current_block}] | Press [ ENTER ] to complete trial...")
        else:
            proceed = input(f"Current Block : [{current_block}] | Press [ ENTER ] to proceed to next block : [{blocks[block_order[idx + 1]]}]")
        continue
            
    
    while True:
        elapsed_time = time.time() - block_start_time
        remaining_time = block_duration - elapsed_time
        
        if remaining_time <= 0:
            break
        

        if not is_final_block: 
            print(f"Current Block : [{current_block}] | Starting [{blocks[block_order[idx + 1]]}] in {remaining_time:.2f} seconds...", end="\r")
        else : 
            print(f"Current Block : [{current_block}] | Remaining time : {remaining_time:.2f} seconds...", end='\r')
        
        
        time.sleep(0.01)  # Sleep to prevent excessive CPU usage
    print()
    logging.info(f"Completed Block : [{current_block}]")
    #print(f"Completed Block : [{current_block}]")

logging.info("Experiment Complete.")

experiment_running = False
if use_ur3:
    ur_socket.close()
    ur_server_thread.join()

import matplotlib.pyplot as plt
plt.plot(pressure_readings)
plt.title("Force Sensor During Experiment")
plt.ylabel("Magnitude")
plt.xlabel("Time")
plt.show()