import ConfigParser
import os
import hashlib

CONFIG_FILE=".acousticbrainz.conf"

settings = {}

def load_settings():
    defaultfile = "abz/default.conf"
    conffile = os.path.join(os.path.expanduser("~"), CONFIG_FILE)
    config = ConfigParser.RawConfigParser()
    config.read(defaultfile)
    if os.path.exists(conffile):
        config.read(conffile)

    settings["host"] = config.get("acousticbrainz", "host")

    essentia = config.get("essentia", "path")
    if not os.path.isabs(essentia):
        essentia = os.path.abspath(essentia)
    if not os.path.exists(essentia):
        raise Exception ("Cannot find the extractor")

    h = hashlib.sha1()
    h.update(open(essentia, "rb").read())
    settings["essentia_path"] = essentia
    settings["essentia_build_sha"] = h.hexdigest()

    extensions = config.get("acousticbrainz", "extensions")
    extensions = [".%s" % e.lower() for e in extensions.split()]
    settings["extensions"] = tuple(extensions)
