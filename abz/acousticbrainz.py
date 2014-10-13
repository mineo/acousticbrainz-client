# Copyright 2014 Music Technology Group - Universitat Pompeu Fabra
# acousticbrainz-client is available under the terms of the GNU
# General Public License, version 3 or higher. See COPYING for more details.

from __future__ import print_function
import futures
import json
import multiprocessing
import os
import subprocess
import tempfile
import urlparse
import uuid
import sqlite3

import requests
import taglib

import config

from sys import exit

config.load_settings()
conn = sqlite3.connect(config.get_sqlite_file())

def add_to_filelist(filepath, reason=None):
    query = """insert into filelog(filename, reason) values(?, ?)"""
    c = conn.cursor()
    r = c.execute(query, (filepath.decode("utf-8"), reason))
    conn.commit()

def is_processed(filepath):
    query = """select * from filelog where filename = ?"""
    c = conn.cursor()
    r = c.execute(query, (filepath.decode("utf-8"), ))
    if len(r.fetchall()):
        return True
    else:
        return False

def get_musicbrainz_recordingid(filepath):
    f = taglib.File(filepath)
    # Historically this was called _TRACKID, but it's a recording id
    if "MUSICBRAINZ_TRACKID" in f.tags:
        recordingid = f.tags["MUSICBRAINZ_TRACKID"]
        if len(recordingid) == 0:
            return None
        # TODO: If there's more than 1 recording id we don't know which
        # one is correct. Would this be an error?
        if isinstance(recordingid, list) and len(recordingid) > 0:
            recordingid = recordingid[0]
        try:
            u = uuid.UUID(recordingid)
            return recordingid
        except ValueError:
            return None

def run_extractor(input_path, output_path):
    """
    :raises subprocess.CalledProcessError: if the extractor exits with a non-zero
                                           return code
    """
    extractor = config.settings["essentia_path"]
    args = [extractor, input_path, output_path]
    subprocess.check_call(args)

def submit_features(recordingid, features):
    featstr = json.dumps(features)

    host = config.settings["host"]
    url = urlparse.urlunparse(('http', host, '/%s/low-level' % recordingid, '', '', ''))
    r = requests.post(url, data=featstr)
    r.raise_for_status()

def extractor_output_file_name(base):
    """
    Returns `base` + ".json" if that file exists and just `base` otherwise.
    """
    maybename = base + os.extsep + "json"
    if os.path.isfile(maybename):
        return maybename
    return base

# codec names from ffmpeg
lossless_codecs = ["alac", "ape", "flac", "shorten", "tak", "truehd", "tta", "wmalossless"]
def process_file(filepath):
    print("Processing file %s" % filepath)
    if is_processed(filepath):
        print(" * already processed, skipping")
        return
    recid = get_musicbrainz_recordingid(filepath)

    if recid:
        print(" - has recid %s" % recid)
        fd, tmpname = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.unlink(tmpname)
        try:
            run_extractor(filepath, tmpname)
        except subprocess.CalledProcessError as e:
            print(" ** The extractor's return code was %s" % e.returncode)
            add_to_filelist(filepath, "extractor")
        else:
            tmpname = extractor_output_file_name(tmpname)
            try:
                features = json.load(open(tmpname))
                features["metadata"]["version"]["essentia_build_sha"] = config.settings["essentia_build_sha"]
                encoder = features["metadata"]["audio_properties"]["codec"]
                # There's a bunch of pcm types, so check them separately
                lossless = encoder in lossless_codecs or encoder.startswith("pcm_")
                features["metadata"]["audio_properties"]["lossless"] = lossless

                try:
                    submit_features(recid, features)
                except requests.exceptions.HTTPError as e:
                    print(" ** Got an error submitting the track. Error was:")
                    print(e.response.text)
                add_to_filelist(filepath)
            except ValueError:
                print(" ** Failed to read the output for this file to submit")
                add_to_filelist(filepath, "json")

        finally:
            tmpname = extractor_output_file_name(tmpname)
            if os.path.isfile(tmpname):
                os.unlink(tmpname)
    else:
        print(" - no recid")

def process_directory(directory_path, executor):
    print("processing directory %s" % directory_path)

    for dirpath, dirnames, filenames in os.walk(directory_path):
        for f in filenames:
            if f.lower().endswith(config.settings["extensions"]):
                yield executor.submit(process_file, (os.path.abspath(os.path.join(dirpath, f))))


def process(path, executor):
    if not os.path.exists(path):
        exit(path + "does not exist")
    path = os.path.abspath(path)
    if os.path.isfile(path):
        yield executor.submit(process_file, path)
    elif os.path.isdir(path):
        yield process_directory(path, executor)

def main(args):
    with futures.ProcessPoolExecutor(args.processes) as executor:
        for path in args.p:
            for f in process(path, executor):
                f.add_done_callback(add_to_filelist)
        executor.shutdown()
