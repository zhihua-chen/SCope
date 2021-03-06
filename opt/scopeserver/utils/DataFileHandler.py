import os
from appdirs import AppDirs
import time
import uuid
import pickle
from pathlib import Path

from scopeserver.dataserver.modules.gserver import GServer as gs

app_name = 'SCope'
app_author = 'Aertslab'

platform_dirs = AppDirs(appname=app_name, appauthor=app_author)

_ONE_DAY_IN_SECONDS = 60 * 60 * 24
_UUID_TIMEOUT = _ONE_DAY_IN_SECONDS * 5
_SESSION_TIMEOUT = 60 * 5

data_dirs = {"Loom": {"path": os.path.join(platform_dirs.user_data_dir, "my-looms"),
                      "message": "No data folder detected. Making loom data folder: {0}.".format(str(os.path.join(platform_dirs.user_data_dir, "my-looms")))},
             "GeneSet": {"path": os.path.join(platform_dirs.user_data_dir, "my-gene-sets"),
                         "message": "No gene-sets folder detected. Making gene-sets data folder in current directory: {0}.".format(str(os.path.join(platform_dirs.user_data_dir, "my-gene-sets")))},
             "LoomAUCellRankings": {"path": os.path.join(platform_dirs.user_data_dir, "my-aucell-rankings"),
                                    "message": "No AUCell rankings folder detected. Making AUCell rankings data folder in current directory: {0}.".format(str(os.path.join(platform_dirs.user_data_dir, "my-aucell-rankings")))},
             "Config": {"path": os.path.join(platform_dirs.user_config_dir),
                        "message": "No Config folder detected. Making Config folder: {0}.".format(str(os.path.join(platform_dirs.user_config_dir)))},
             "Logs": {"path": os.path.join(platform_dirs.user_log_dir),
                      "message": "No Logs folder detected. Making Logs folder: {0}.".format(str(os.path.join(platform_dirs.user_log_dir)))}}

class DataFileHandler():

    data_dirs = data_dirs

    def __init__(self, dev_env):
        self.dev_env = dev_env
        self.current_UUIDs = {}
        self.permanent_UUIDs = set()
        self.active_sessions = {}
        self.uuid_log = None
        self.data_dirs =  data_dirs
        self.gene_sets_dir = DataFileHandler.get_data_dir_path_by_file_type(file_type="GeneSet")
        self.rankings_dir = DataFileHandler.get_data_dir_path_by_file_type(file_type="LoomAUCellRankings")
        self.config_dir = DataFileHandler.get_data_dir_path_by_file_type(file_type="Config")
        self.logs_dir = DataFileHandler.get_data_dir_path_by_file_type(file_type="Logs")
        self.create_global_dirs()
        self.create_uuid_log()
    
    def get_gene_sets_dir(self):
        return self.gene_sets_dir

    def get_config_dir(self):
        return self.config_dir

    def get_gobal_sets(self):
        return self.global_sets

    def get_global_rankings(self):
        return self.global_rankings
    
    def set_global_data(self):
        self.global_sets = [x for x in os.listdir(self.gene_sets_dir) if not os.path.isdir(os.path.join(self.gene_sets_dir, x))]
        self.global_rankings = [x for x in os.listdir(self.rankings_dir) if not os.path.isdir(os.path.join(self.rankings_dir, x))]

    @staticmethod
    def get_data_dir_path_by_file_type(file_type, UUID=None):
        if file_type in ['Loom', 'GeneSet', 'LoomAUCellRankings'] and UUID is not None:
            globalDir = data_dirs[file_type]["path"]
            UUIDDir = os.path.join(globalDir, UUID)
            return UUIDDir
        return data_dirs[file_type]["path"]

    @staticmethod
    def get_data_dirs():
        return data_dirs
    
    def create_global_dirs(self):
        for data_type in self.data_dirs.keys():
            if not os.path.isdir(data_dirs[data_type]["path"]):
                print(self.data_dirs[data_type]["message"])
                os.makedirs(self.data_dirs[data_type]["path"])
    
    def get_current_UUIDs(self):
        return self.current_UUIDs

    def get_permanent_UUIDs(self):
        return self.permanent_UUIDs

    def read_UUID_db(self):
        if os.path.isfile(os.path.join(self.config_dir, 'UUID_Timeouts.tsv')):
            with open(os.path.join(self.config_dir, 'UUID_Timeouts.tsv'), 'r') as fh:
                for line in fh.readlines():
                    ls = line.rstrip('\n').split('\t')
                    self.current_UUIDs[ls[0]] = float(ls[1])
        if os.path.isfile(os.path.join(self.config_dir, 'Permanent_Session_IDs.txt')):
            with open(os.path.join(self.config_dir, 'Permanent_Session_IDs.txt'), 'r') as fh:
                for line in fh.readlines():
                    self.permanent_UUIDs.add(line.rstrip('\n'))
                    self.current_UUIDs[line.rstrip('\n')] = time.time() + (_ONE_DAY_IN_SECONDS * 365)
        else:
            with open(os.path.join(self.config_dir, 'Permanent_Session_IDs.txt'), 'w') as fh:
                newUUID = 'SCopeApp__{0}'.format(str(uuid.uuid4()))
                fh.write('{0}\n'.format(newUUID))
                self.current_UUIDs[newUUID] = time.time() + (_ONE_DAY_IN_SECONDS * 365)

    def update_UUID_db(self):
        with open(os.path.join(self.config_dir, 'UUID_Timeouts.tsv'), 'w') as fh:
            for UUID in self.current_UUIDs.keys():
                if UUID not in self.permanent_UUIDs:
                    fh.write('{0}\t{1}\n'.format(UUID, self.current_UUIDs[UUID]))
        if os.path.isfile(os.path.join(self.config_dir, 'Permanent_Session_IDs.txt')):
            with open(os.path.join(self.config_dir, 'Permanent_Session_IDs.txt'), 'r') as fh:
                for line in fh.readlines():
                    self.permanent_UUIDs.add(line.rstrip('\n'))
                    self.current_UUIDs[line.rstrip('\n')] = time.time() + (_ONE_DAY_IN_SECONDS * 365)
    
    def get_uuid_log(self):
        return self.uuid_log

    def create_uuid_log(self):
        self.uuid_log = open(os.path.join(self.logs_dir, 'UUID_Log_{0}'.format(time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime()))), 'w')
    
    def get_active_sessions(self):
        return self.active_sessions

    def active_session_check(self):
        curTime = time.time()
        for UUID in list(self.active_sessions.keys()):
            if curTime - self.active_sessions[UUID] > _SESSION_TIMEOUT or UUID not in self.get_current_UUIDs():
                del(self.active_sessions[UUID])
    
    def reset_active_session_timeout(self, UUID):
        self.active_sessions[UUID] = time.time()

    def load_gene_mappings(self):
        gene_mappings_dir_path = os.path.join(Path(__file__).parents[1], 'dataserver', 'data', 'gene_mappings') if self.dev_env else os.path.join(Path(__file__).parents[4], 'data', 'gene_mappings')
        DataFileHandler.dmel_mappings = pickle.load(open(os.path.join(gene_mappings_dir_path, 'terminal_mappings.pickle'), 'rb'))
        DataFileHandler.hsap_to_dmel_mappings = pickle.load(open(os.path.join(gene_mappings_dir_path, 'hsap_to_dmel_mappings.pickle'), 'rb'))
        DataFileHandler.mmus_to_dmel_mappings = pickle.load(open(os.path.join(gene_mappings_dir_path, 'mmus_to_dmel_mappings.pickle'), 'rb'))