
import os
import time
import datetime
import socket
import logging
import threading
import json
from pylsl import StreamInfo, StreamOutlet  

# Experiment Configuration
experiment_name = "Post_CVit_TwoHand".replace(" ", "_")
conducted_time = datetime.datetime.now()
subject_id = 3
trial_number = 2

comment = ""

# Incoming messages from the UR3 are compared to the markers table,
# if the messgae is found the ID is sent as a marker
# If we're using ur3, how is the block design ran?
# Using the UR3 we cannot rely on the accurate timings in this script,
# meaning the block design should be passive
blockless = True

# Block Design
blocks = [ "Rest", "LEft"]
durations = [ 20, 10, ] # Seconds
block_order = [ 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1] # NOTE : This are indices into the Blocks array
wait_for_input_blocks = [ False, False ] # If True : to proceed to next block, a manual input is needed

# Baseline Configuration
baseline_duration = 30 # 30s pre and post baselines
use_baseline = False

# NOTE : We need to test wheter or not g.Recorder can handle values above 9
markers = {
        "Rest" : 0,
        "Drawing" : 1,
}

use_fnirs   = True # Send Markers to aurora
use_eeg     = True # Send Markers to gRecorder
use_ur3     = False # NOTE : This starts a seperate program thread handling the connection


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
        "use_ur3" : use_ur3,
    }
    filename = experiment_name + "_" + conducted_time.strftime("%d_%m_%Y_%H_%M_%S") + "subject_" + str(subject_id) +  "_trial_" + str(trial_number) + ".json"
    filepath = "logs/" + filename 

    with open(filepath, "w") as json_file:
        json.dump(encoded, json_file, indent=4)
    json_file.close()
save_experiment_to_file()

def setup_logging(): # NOTE : Use logging.debug|info|error|warning to write to screen and console, use printf for only console
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


# UR3 Server Connection Configuration
UR_SERVER_HOST = '192.168.0.101'  # Listen on all interfaces
UR_SERVER_PORT = 32000  # Choose an appropriate port
BUFFER_SIZE = 1024

def handle_ur_connection(client_socket:socket.socket, client_address):
    """Service the UR3 connection"""
    try:
        while True:
            data = client_socket.recv(BUFFER_SIZE)
            if not data:
                logging.info(f"UR Server : Client {client_address} disconnected...")
                break

            try:
                message = data.decode('utf-8').strip()
                logging.info(f"UR Server : Received message from UR3 : {message}") # Only put this into the log file, dont print to console

                if message in markers:
                    push_marker(markers[message])
                else:
                    logging.info(f"Unknown message from controller: {message}")

            except UnicodeDecodeError:
                logging.error("UR Server : Invalid data received from controller.")
            except Exception as e:
                logging.error(f"UR Server : Error processing controller data: {e}")
                break

    except Exception as e:
        logging.error(f"UR Server : Handler Error : {e}")
    finally:
        client_socket.close()
        logging.info(f"UR Server : Client connection {client_address} closed...")

def start_ur_server():
    """Start UR3 server (or intermediate computer)"""
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # 
        server_socket.bind((UR_SERVER_HOST, UR_SERVER_PORT)) # 
        server_socket.listen(1)

        logging.info(f"UR Server : Listening on {UR_SERVER_HOST}:{UR_SERVER_PORT}")

        while True:  # Accept multiple client connections
            client_socket, client_address = server_socket.accept()
            logging.info(f"UR Server : Accepted connection from client {client_address}")
            client_thread = threading.Thread(target=handle_ur_connection, args=(client_socket, client_address))
            client_thread.daemon = True # allow program to exit if thread is running
            client_thread.start()

    except Exception as e:
        logging.error(f"UR Server : Error: {e}")
    finally:
        if 'server_socket' in locals():
            server_socket.close()
            logging.info("UR Server : Stopped...")

if use_ur3:       
    ur_server_thread = threading.Thread(target=start_ur_server) # Create a server thread
    ur_server_thread.daemon = True # Kill thread when program exits
    ur_server_thread.start() # Start server

def push_marker(marker:int):
    if use_fnirs:
        fnirs_outlet.push_sample([marker]) 
    if use_eeg: # NOTE : This is already encoded to bytes
        xml_msg = fill_grecorder_xml_msg(marker)
        eeg_socket.sendto(xml_msg.encode(), (eeg_target_ip, eeg_target_port)) 
    if use_ur3:
       # the robot doesnt receieve any markers
       pass
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
        
        print(f"\nStarted Block : [{current_block}]")
        print(f"Order : {block_order_with_active_border(idx)}")
        
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
                print(f"Current Block : [{current_block}] | Starting [{blocks[block_order[idx + 1]]}] in {remaining_time:.2f} seconds...", end="\r")
            else: 
                print(f"Current Block : [{current_block}] | Remaining time : {remaining_time:.2f} seconds...", end='\r')


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
        
        print(f"Baseline : Remaining time : {remaining_time:.2f} seconds...", end='\r')
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
        
        print(f"Baseline : Remaining time : {remaining_time:.2f} seconds...", end='\r')
        time.sleep(0.1)
    push_marker(markers["End"])
    logging.info(f"Completed Post-block design baseline : {baseline_duration} seconds")
                    

if use_baseline:
    ready = input(f"Press [ ENTER ] to start {baseline_duration} second baseline recording")
    record_pre_trial_baseline()

 # CONDUCT BLOCK DESIGN
if not blockless:
    run_block_design()
    
if blockless:
    while True:
        # How do we run blockless ? 
        # This just sits waiting for UR3 robot messages, or manual entry
        
        for marker_name, marker_value in markers.items():
           print(f" [ {marker_name} ] : {marker_value}")
        # print options
        # N = Complete block design and start post-block baseline
        print(f" [ N ] : Complete block design and start {baseline_duration} second baseline recording")
        ans = input("Command : ")
        
        if ans.upper() == "N":
            break

        push_marker(int(ans))
if use_baseline:
    record_post_trial_baseline()
    

logging.info("Experiment Complete.")
exit() # Threads should close automatically
