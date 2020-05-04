# Klippy custom exceptions handler.
# 
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
# 
# Examples at the end of this file.

import logging
from text import msg
logger = logging.getLogger(__name__)

# Klippy Error
class KError(Exception):
    def __init__(self, *args):
#        except (configfile.error, error) as e:
#            logger.exception("Config error")
#            self._set_status("%s %s" % (str(e), msg("restart")))
#            return
#        except msgproto.error as e:
#            logger.exception("Protocol error")
#            self._set_status("%s %s" % (str(e), msg("errorproto")))
#            return
#        except error as e:
#            logger.exception("MCU error during connect")
#            self._set_status("%s %s" % (str(e), msg("errormcuconnect")))
#            return
#        except Exception as e:
#            logger.exception("Unhandled exception during connect")
#            self._set_status("Internal error during connect: %s\n%s" % (str(e), msg("restart"),))
#            return
        pass
    def msg(self):
        return "TODO"
    def status(self):
        return "TODO"
