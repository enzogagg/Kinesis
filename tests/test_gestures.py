import pytest
import math
from leap_lock import is_fist, is_pinch, is_index_up, is_open

class MockLandmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class MockHand:
    def __init__(self, coordinates):
        # We need 21 landmarks for a full mediapipe hand
        self.landmark = [MockLandmark(x, y) for (x, y) in coordinates]

def create_mock_hand(pose_type="open"):
    """Creates a 21-landmark mock hand based on simple geometric poses."""
    lm = [(0.0, 0.0) for _ in range(21)]
    lm[0] = (0.5, 0.9)  # Wrist at bottom center
    
    # Thumb (base to tip)
    lm[1], lm[2], lm[3], lm[4] = (0.4, 0.8), (0.3, 0.7), (0.2, 0.6), (0.1, 0.5)
    # Index
    lm[5], lm[6], lm[7], lm[8] = (0.4, 0.6), (0.4, 0.4), (0.4, 0.2), (0.4, 0.1)
    # Middle
    lm[9], lm[10], lm[11], lm[12] = (0.5, 0.6), (0.5, 0.4), (0.5, 0.2), (0.5, 0.1)
    # Ring
    lm[13], lm[14], lm[15], lm[16] = (0.6, 0.6), (0.6, 0.4), (0.6, 0.2), (0.6, 0.1)
    # Pinky
    lm[17], lm[18], lm[19], lm[20] = (0.7, 0.6), (0.7, 0.5), (0.7, 0.4), (0.7, 0.3)

    if pose_type == "fist":
        # Curl all fingers (tip closer to wrist than pip)
        for tip, pip in [(8,6), (12,10), (16,14), (20,18)]:
            lm[tip] = (lm[pip][0], 0.8) # Move tip down below pip
            
    elif pose_type == "pinch":
        # Thumb tip and index tip at same location
        pinch_pt = (0.4, 0.3)
        lm[4] = pinch_pt
        lm[8] = pinch_pt
        
    elif pose_type == "index_up":
        # Curl middle, ring, pinky, and thumb
        for tip, pip in [(12,10), (16,14), (20,18)]:
            lm[tip] = (lm[pip][0], 0.8)
        # Curl thumb
        lm[4] = (0.6, 0.8)
        
    return MockHand(lm)


def test_is_fist():
    open_hand = create_mock_hand("open")
    assert not is_fist(open_hand)
    
    fist_hand = create_mock_hand("fist")
    assert is_fist(fist_hand)

def test_is_open():
    open_hand = create_mock_hand("open")
    assert is_open(open_hand)
    
    fist_hand = create_mock_hand("fist")
    assert not is_open(fist_hand)

def test_is_pinch():
    pinch_hand = create_mock_hand("pinch")
    assert is_pinch(pinch_hand)
    
    open_hand = create_mock_hand("open")
    assert not is_pinch(open_hand)

def test_is_index_up():
    index_hand = create_mock_hand("index_up")
    assert is_index_up(index_hand)
    
    open_hand = create_mock_hand("open")
    assert not is_index_up(open_hand)
    
    fist_hand = create_mock_hand("fist")
    assert not is_index_up(fist_hand)
