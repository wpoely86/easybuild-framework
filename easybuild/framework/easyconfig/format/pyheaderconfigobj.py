# #
# Copyright 2013-2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
# #

"""
The main easyconfig format class

@author: Stijn De Weirdt (Ghent University)
"""
import re

from vsc import fancylogger

from easybuild.framework.easyconfig.constants import EASYCONFIG_CONSTANTS
from easybuild.framework.easyconfig.format.format import get_format_version, EasyConfigFormat
from easybuild.framework.easyconfig.licenses import EASYCONFIG_LICENSES_DICT
from easybuild.framework.easyconfig.templates import TEMPLATE_CONSTANTS
from easybuild.tools.configobj import ConfigObj
from easybuild.tools.systemtools import get_shared_lib_ext

_log = fancylogger.getLogger('easyconfig.format.pyheaderconfigobj', fname=False)


def build_easyconfig_constants_dict():
    """Make a dictionary with all constants that can be used"""
    # sanity check
    all_consts = [
        ('TEMPLATE_CONSTANTS', dict([(x[0], x[1]) for x in TEMPLATE_CONSTANTS])),
        ('EASYCONFIG_CONSTANTS', dict([(x[0], x[1]) for x in EASYCONFIG_CONSTANTS])),
        ('EASYCONFIG_LICENSES', EASYCONFIG_LICENSES_DICT),
    ]
    err = []
    const_dict = {}

    for (name, csts) in all_consts:
        for cst_key, cst_val in csts.items():
            ok = True
            for (other_name, other_csts) in all_consts:
                if name == other_name:
                    continue
                # make sure that all constants only belong to one name
                if cst_key in other_csts:
                    err.append('Found name %s from %s also in %s' % (cst_key, name, other_name))
                    ok = False
            if ok:
                const_dict[cst_key] = cst_val

    if len(err) > 0:
        _log.error("EasyConfig constants sanity check failed: %s" % ("\n".join(err)))
    else:
        return const_dict


def build_easyconfig_variables_dict():
    """Make a dictionary with all variables that can be used"""
    _log.deprecated("Magic 'global' easyconfigs variables like shared_lib_ext should no longer be used", '2.0')
    vars_dict = {
        "shared_lib_ext": get_shared_lib_ext(),  # FIXME: redeprecate this
    }

    return vars_dict


class EasyConfigFormatConfigObj(EasyConfigFormat):
    """
    Extended EasyConfig format, with support for a header and sections that are actually parsed (as opposed to exec'ed).
    It's very limited for now, but is already huge improvement.

    4 parts in text file

    - header (^# style)
    - docstring
    - pyheader
     - exec txt, extract doctstring and remainder
    - begin of regular section until EOF
     - feed to ConfigObj
    """

    PYHEADER_ALLOWED_BUILTINS = []  # default no builtins

    def __init__(self, *args, **kwargs):
        """Extend EasyConfigFormat with some more attributes"""
        super(EasyConfigFormatConfigObj, self).__init__(*args, **kwargs)

        self.pyheader_localvars = None
        self.configobj = None

    def parse(self, txt, strict_section_markers=False):
        """
        Pre-process txt to extract header, docstring and pyheader
        """
        # where is the first section?
        sectionmarker_pattern = ConfigObj._sectionmarker.pattern
        if strict_section_markers:
            # don't allow indentation for section markers
            sectionmarker_pattern = re.sub('^.*?indentation.*$', '', sectionmarker_pattern, flags=re.M)
        regex = re.compile(sectionmarker_pattern, re.VERBOSE | re.M)
        reg = regex.search(txt)
        if reg is None:
            # no section
            self.log.debug("No section found.")
            start_section = None
        else:
            start_section = reg.start()
            self.log.debug('Section starts at idx %s' % start_section)

        self.parse_pre_section(txt[:start_section])
        if start_section is not None:
            self.parse_section(txt[start_section:])

    def parse_pre_section(self, txt):
        """Parse the text block before the start of the section"""
        header_reg = re.compile(r'^\s*(#.*)?$')

        txt_list = txt.split('\n')

        header_text = []

        while len(txt_list) > 0:
            line = txt_list.pop(0)

            format_version = get_format_version(line)
            if format_version is not None:
                if not format_version == self.VERSION:
                    self.log.error("Invalid version %s for current format class" % (format_version))
                # version is not part of header
                continue

            r = header_reg.search(line)
            if not r:
                # put the line back
                txt_list.insert(0, line)
                break
            header_text.append(line)

        self.parse_header('\n'.join(header_text))
        self.parse_pyheader('\n'.join(txt_list))

    def parse_header(self, header):
        """Parse the header, assign to self.header"""
        # FIXME: do something with the header
        self.log.debug("Found header %s" % header)
        self.header = header

    def parse_pyheader(self, pyheader):
        """Parse the python header, assign to docstring and cfg"""
        global_vars, local_vars = self.pyheader_env()
        self.log.debug("pyheader initial global_vars %s" % global_vars)
        self.log.debug("pyheader initial local_vars %s" % local_vars)
        self.log.debug("pyheader text being exec'ed: %s" % pyheader)

        try:
            exec(pyheader, global_vars, local_vars)
        except SyntaxError, err:
            self.log.error("SyntaxError in easyconfig pyheader %s: %s" % (pyheader, err))

        self.log.debug("pyheader final global_vars %s" % global_vars)
        self.log.debug("pyheader final local_vars %s" % local_vars)

        if '__doc__' in local_vars:
            self.docstring = local_vars.pop('__doc__')
        else:
            self.log.debug('No docstring found in local_vars')

        self.pyheader_localvars = local_vars

    def pyheader_env(self):
        """Create the global/local environment to use with eval/execfile"""
        local_vars = {}
        global_vars = {}

        # all variables
        global_vars.update(build_easyconfig_variables_dict())
        # all constants
        global_vars.update(build_easyconfig_constants_dict())

        # allowed builtins
        if self.PYHEADER_ALLOWED_BUILTINS is not None:
            current_builtins = globals()['__builtins__']
            builtins = {}
            for name in self.PYHEADER_ALLOWED_BUILTINS:
                if isinstance(current_builtins, dict) and name in current_builtins:
                    # in unittest environment? FIXME: clarify this
                    builtins[name] = current_builtins.get(name)
                elif hasattr(current_builtins, name):
                    builtins[name] = getattr(current_builtins, name)
                else:
                    self.log.warning('No builtin %s found.' % name)
            global_vars['__builtins__'] = builtins
            self.log.debug("Available builtins: %s" % global_vars['__builtins__'])

        return global_vars, local_vars

    def parse_section(self, section):
        """Parse the section block"""
        try:
            cfgobj = ConfigObj(section.split('\n'))
        except SyntaxError, err:
            self.log.error('Failed to convert section text %s: %s' % (section, err))

        self.log.debug("Found ConfigObj instance %s" % cfgobj)

        self.configobj = cfgobj
