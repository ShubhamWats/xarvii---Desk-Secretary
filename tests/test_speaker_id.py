import numpy as np
import pytest

from deskd.skills.speaker_id import SpeakerID


def make_sid(threshold=0.72, tmp=None):
    sid = SpeakerID(threshold=threshold,
                    state_file=f"/tmp/test-voice-{abs(hash(str(tmp)))}.json")
    sid.reset()
    return sid


def test_enroll_and_verify_math(tmp_path):
    sid = make_sid(tmp=str(tmp_path))
    rng = np.random.default_rng(1)
    owner = rng.normal(size=256)
    owner /= np.linalg.norm(owner)
    sid.save_centroid(owner)
    # bypass audio: score directly against centroid
    def score(vec):
        return float(np.dot(vec, sid.centroid) /
                     ((np.linalg.norm(vec) * np.linalg.norm(sid.centroid)) or 1))
    assert score(owner) > sid.threshold          # owner passes
    stranger = -owner                             # opposite direction
    assert score(stranger) < sid.threshold        # guest fails


def test_unenrolled_is_none(tmp_path):
    sid = make_sid(tmp=str(tmp_path))
    assert sid.enrolled() is False


def test_reset(tmp_path):
    sid = make_sid(tmp=str(tmp_path))
    sid.save_centroid(np.ones(64) / 8)
    sid.reset()
    assert not sid.enrolled()
