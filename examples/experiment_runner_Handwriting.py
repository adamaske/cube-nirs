# experiment_runner_handwriting.py
import os, time, datetime, socket, logging, threading, json, queue
from pylsl import StreamInfo, StreamOutlet, cf_int32
from ui_window import start_ui

# --- Config / Paths ---
use_ui = True
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Defaults (can be overridden by staging form)
experiment_name = "HandWriting_Pilot".replace(" ", "_")
conducted_time = datetime.datetime.now()
subject_id = 4
trial_number = 1
comment = ""

# Words that Word1/2/3 represent
display_words = ["HELLO", "BANANA", "WRITING"]

# Block Design
blockless = False
blocks = ["Rest", "Word1", "Word2", "Word3"]
durations = [20, 15, 15, 15]
# Example short sequence for testing; extend as needed
block_order = [0, 1, 0, 2, 0, 3, 0]
wait_for_input_blocks = [False, False, False, False]

# Baseline
baseline_duration = 30
use_baseline = False

# Markers
markers = {"Start": 99, "End": 100, "Rest": 0, "Word1": 1, "Word2": 2, "Word3": 3}

use_fnirs = True
use_eeg = True

# Queues
ui_queue = queue.Queue()   # experiment → UI
cmd_queue = queue.Queue()  # UI → experiment

# --- Validation ---
def validate_block_design():
    assert len(durations) == len(blocks)
    for block_idx in block_order:
        assert 0 <= block_idx < len(blocks)
    assert len(wait_for_input_blocks) == len(blocks)
validate_block_design()

# --- Pretty plan ---
def print_experiment_description():
    print(f"Welcome To Experiment : {experiment_name}")
    try:
        print(f"Conducted : {conducted_time.ctime()}")
    except Exception:
        print("Conducted : (unset)")
    print(f"Subject ID : {subject_id}")
    print(f"Trial : {trial_number}")
    print("Block Order : ", "->".join(blocks[i] for i in block_order) + "->End")

# --- Persist config (called after Start) ---
def save_experiment_to_file():
    encoded = {
        "experiment_name": experiment_name,
        "date_time": conducted_time.strftime("%d_%m_%Y_%H_%M_%S"),
        "subject_ID": subject_id,
        "trial_number": trial_number,
        "blocks": blocks,
        "durations": durations,
        "block_order": block_order,
        "block_wait_for_input": wait_for_input_blocks,
        "markers": markers,
        "using_fnirs": use_fnirs,
        "using_eeg": use_eeg,
        "comment": comment,
    }
    filename = (
        f"{experiment_name}_{conducted_time.strftime('%d_%m_%Y_%H_%M_%S')}"
        f"subject_{subject_id}_trial_{trial_number}.json"
    )
    with open(os.path.join(LOG_DIR, filename), "w", encoding="utf-8") as f:
        json.dump(encoded, f, indent=4)

# --- Logging (called after Start) ---
def setup_logging():
    log_filename = (
        f"{experiment_name}_{conducted_time.strftime('%d_%m_%Y_%H_%M_%S')}"
        f"subject_{subject_id}_trial_{trial_number}.log"
    )
    log_filepath = os.path.join(LOG_DIR, log_filename)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_filepath, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.getLogger().handlers[0].level = logging.DEBUG
    logging.getLogger().handlers[1].level = logging.INFO

# --- EEG (UDP) ---
eeg_target_ip = "127.0.0.1"
eeg_target_port = 1000
eeg_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def fill_grecorder_xml_msg(value):
    return f'<gRecorder><DAQ.KeyboardMarkerUdpMessage assembly="gRecorder" name="{value}"/></gRecorder>'

# --- fNIRS (LSL) ---
stream_name = "Trigger"; stream_type = "Markers"; stream_channels = 1; stream_id = "ADEPT"
fnirs_info = StreamInfo(name=stream_name, type=stream_type, channel_count=stream_channels,
                        channel_format=cf_int32, source_id=stream_id)
fnirs_outlet = StreamOutlet(fnirs_info)

def push_marker(marker: int):
    if use_fnirs:
        fnirs_outlet.push_sample([marker])
    if use_eeg:
        xml = fill_grecorder_xml_msg(marker)
        eeg_socket.sendto(xml.encode(), (eeg_target_ip, eeg_target_port))
    logging.debug("Pushed marker : %s", marker)

def block_order_with_active_border(active_idx: int) -> str:
    parts = []
    for idx, bidx in enumerate(block_order):
        name = blocks[bidx]
        parts.append(f"[{name.upper()}]" if idx == active_idx else name)
    return "->".join(parts) + "->END"

def run_block_design():
    for idx, bidx in enumerate(block_order):
        block_onset = time.time()
        current_block = blocks[bidx]
        block_duration = durations[bidx]
        is_final_block = (idx == len(block_order) - 1)

        logging.info("Started Block : [%s]", current_block)
        print(f"\\nStarted Block : [{current_block}]")
        print(f"Order : {block_order_with_active_border(idx)}")

        # Tell UI (richer message for timer + next)
        if use_ui:
            try:
                next_block = blocks[block_order[idx + 1]] if not is_final_block else None
                ui_queue.put(("block_start", current_block, block_duration, block_onset, next_block))
            except Exception:
                pass

        # Push marker matching the block index (your convention)
        push_marker(bidx)

        # Manual gate?
        if wait_for_input_blocks[bidx]:
            prompt = (f"Current Block : [{current_block}] | Press [ ENTER ] to complete trial..."
                      if is_final_block else
                      f"Current Block : [{current_block}] | Press [ ENTER ] to proceed to next block : [{blocks[block_order[idx + 1]]}]")
            input(prompt); continue

        # Auto timer
        while True:
            remaining = block_duration - (time.time() - block_onset)
            if remaining <= 0:
                break
            nxt = blocks[block_order[idx + 1]] if not is_final_block else None
            if nxt:
                print(f"Current Block : [{current_block}] | Starting [{nxt}] in {remaining:.2f} seconds...", end="\\r")
            else:
                print(f"Current Block : [{current_block}] | Remaining time : {remaining:.2f} seconds...", end="\\r")
            time.sleep(0.1)

    print()
    logging.info("Completed Block : [%s]", current_block)

    # Notify UI so it can flush final Word block buffer
    if use_ui:
        try:
            ui_queue.put(("experiment_end",))
        except Exception:
            pass

def record_pre_trial_baseline():
    logging.info("Started Pre-block design baseline : %ss", baseline_duration)
    push_marker(markers["Start"])
    start = time.time()
    while True:
        remaining = baseline_duration - (time.time() - start)
        if remaining <= 0: break
        print(f"Baseline : Remaining time : {remaining:.2f} seconds...", end="\\r")
        time.sleep(0.1)
    logging.info("Completed Pre-block design baseline : %ss", baseline_duration)

def record_post_trial_baseline():
    logging.info("Started Post-block design baseline : %ss", baseline_duration)
    start = time.time()
    while True:
        remaining = baseline_duration - (time.time() - start)
        if remaining <= 0: break
        print(f"Baseline : Remaining time : {remaining:.2f} seconds...", end="\\r")
        time.sleep(0.1)
    push_marker(markers["End"])
    logging.info("Completed Post-block design baseline : %ss", baseline_duration)

def _experiment_entrypoint():
    print_experiment_description()
    # set up logging now that config is final
    setup_logging()
    logging.info(f"g.Recorder : UDP socket established {eeg_target_ip} : {eeg_target_port}")
    logging.info(f"LSL outlet established {stream_name}:{stream_type}, {stream_channels}xint32 @ {stream_id}")

    if use_baseline:
        input(f"Press [ ENTER ] to start {baseline_duration} second baseline recording")
        record_pre_trial_baseline()

    if not blockless:
        run_block_design()
    else:
        while True:
            for k, v in markers.items():
                print(f" [ {k} ] : {v}")
            print(f" [ N ] : Complete block design and start {baseline_duration} second baseline recording")
            ans = input("Command : ")
            if ans.upper() == "N":
                break
            try:
                push_marker(int(ans))
            except ValueError:
                logging.warning("Invalid input (not an int): %s", ans)

    if use_baseline:
        record_post_trial_baseline()

    save_experiment_to_file()
    logging.info("Experiment Complete.")

def wait_for_start():
    """Wait for UI to send ('start_experiment', config_dict)."""
    global experiment_name, conducted_time, subject_id, trial_number, comment
    print("Waiting for Start button...")
    while True:
        cmd = cmd_queue.get()
        if cmd[0] == "start_experiment":
            cfg = cmd[1]
            experiment_name = cfg.get("experiment_name", experiment_name)
            # If conducted_time not provided by UI, use 'now'
            conducted_time = datetime.datetime.now()
            subject_id = int(cfg.get("subject_id", subject_id))
            trial_number = int(cfg.get("trial_number", trial_number))
            comment = cfg.get("comment", "")
            print("Start command received!")
            break

if __name__ == "__main__":
    if use_ui:
        def runner():
            wait_for_start()
            _experiment_entrypoint()
        worker = threading.Thread(target=runner, daemon=True)
        worker.start()
        # pass LOG_DIR so the UI can write the keyboard CSV next to logs
        start_ui(ui_queue, cmd_queue, display_words, LOG_DIR)
    else:
        _experiment_entrypoint()
