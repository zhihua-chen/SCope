from concurrent import futures
import sys
import time
import grpc
import loompy as lp
from loompy import timestamp
from loompy import _version
import os
import re
import numpy as np
import pandas as pd
import shutil
import json
import zlib
import base64
import threading
import pickle
import uuid
from collections import OrderedDict, defaultdict
from functools import lru_cache
from itertools import compress
from pathlib import Path

from scopeserver.dataserver.modules.gserver import s_pb2
from scopeserver.dataserver.modules.gserver import s_pb2_grpc
from scopeserver.utils import SysUtils as su
from scopeserver.utils import LoomFileHandler as lfh
from scopeserver.utils import DataFileHandler as dfh
from scopeserver.utils import GeneSetEnrichment as _gse
from scopeserver.utils import CellColorByFeatures as ccbf
from scopeserver.utils import Constant
from scopeserver.utils import SearchSpace as ss
from scopeserver.utils.Loom import Loom

from pyscenic.genesig import GeneSignature
from pyscenic.aucell import create_rankings, enrichment, enrichment4cells

hexarr = np.vectorize('{:02x}'.format)

uploadedLooms = defaultdict(lambda: set())

class SCope(s_pb2_grpc.MainServicer):

    app_name = 'SCope'
    app_author = 'Aertslab'

    def __init__(self):
        self.dfh = dfh.DataFileHandler(dev_env=SCope.dev_env)
        self.lfh = lfh.LoomFileHandler()

        self.dfh.load_gene_mappings()
        self.dfh.set_global_data()
        self.lfh.set_global_data()
        self.dfh.read_UUID_db()

    def update_global_data(self):
        self.dfh.set_global_data()
        self.lfh.set_global_data()

    @lru_cache(maxsize=256)
    def get_features(self, loom, query):
        print(query)
        start_time = time.time()
        if query.startswith('hsap\\'):
            search_space = ss.SearchSpace(loom=loom, cross_species='hsap').build()
            cross_species = 'hsap'
            query = query[5:]
        elif query.startswith('mmus\\'):
            search_space = ss.SearchSpace(loom=loom, cross_species='mmus').build()
            cross_species = 'mmus'
            query = query[5:]
        else:
            search_space = ss.SearchSpace(loom=loom).build()
            cross_species = ''
        print("Debug: %s seconds elapsed making search space ---" % (time.time() - start_time))    
        print(query)

        # Filter the genes by the query

        # Allow caps innsensitive searching, minor slowdown
        start_time = time.time()
        res = []

        queryCF = query.casefold()
        res = [x for x in search_space.keys() if queryCF in x[0]]

        for n, r in enumerate(res):
            if query in r[0]:
                r = res.pop(n)
                res = [r] + res
        for n, r in enumerate(res):
            if r[0].startswith(queryCF):
                r = res.pop(n)
                res = [r] + res
        for n, r in enumerate(res):
            if r[0] == queryCF:
                r = res.pop(n)
                res = [r] + res
        for n, r in enumerate(res):
            if r[1] == query:
                r = res.pop(n)
                res = [r] + res

        # These structures are a bit messy, but still fast
        # r = (elementCF, element, elementName)
        # dg = (drosElement, %match)
        # searchSpace[r] = translastedElement
        collapsedResults = OrderedDict()
        if cross_species == '':
            for r in res:
                if (search_space[r], r[2]) not in collapsedResults.keys():
                    collapsedResults[(search_space[r], r[2])] = [r[1]]
                else:
                    collapsedResults[(search_space[r], r[2])].append(r[1])
        elif cross_species == 'hsap':
            for r in res:
                for dg in self.dfh.hsap_to_dmel_mappings[search_space[r]]:
                    if (dg[0], r[2]) not in collapsedResults.keys():
                        collapsedResults[(dg[0], r[2])] = (r[1], dg[1])
        elif cross_species == 'mmus':
            for r in res:
                for dg in self.dfh.mmus_to_dmel_mappings[search_space[r]]:
                    if (dg[0], r[2]) not in collapsedResults.keys():
                        collapsedResults[(dg[0], r[2])] = (r[1], dg[1])

        descriptions = []
        if cross_species == '':
            for r in collapsedResults.keys():
                synonyms = sorted([x for x in collapsedResults[r]])
                try:
                    synonyms.remove(r[0])
                except ValueError:
                    pass
                if len(synonyms) > 0:
                    descriptions.append('Synonym of: {0}'.format(', '.join(synonyms)))
                else:
                    descriptions.append('')
        elif cross_species == 'hsap':
            for r in collapsedResults.keys():
                descriptions.append('Orthologue of {0}, {1:.2f}% identity (Human -> Drosophila)'.format(collapsedResults[r][0], collapsedResults[r][1]))
        elif cross_species == 'mmus':
            for r in collapsedResults.keys():
                descriptions.append('Orthologue of {0}, {1:.2f}% identity (Mouse -> Drosophila)'.format(collapsedResults[r][0], collapsedResults[r][1]))
        # if mapping[result] != result: change title and description to indicate synonym

        print("Debug: " + str(len(res)) + " genes matching '" + query + "'")
        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        res = {'feature': [r[0] for r in collapsedResults.keys()],
               'featureType': [r[1] for r in collapsedResults.keys()],
               'featureDescription': descriptions}
        return res

    def compressHexColor(self, a):
        a = int(a, 16)
        a_hex3d = hex(a >> 20 << 8 | a >> 8 & 240 | a >> 4 & 15)
        return a_hex3d.replace("0x", "")

    @staticmethod
    def get_vmax(vals):
        maxVmax = max(vals)
        vmax = np.percentile(vals, 99)
        if vmax == 0 and max(vals) != 0:
            vmax = max(vals)
        if vmax == 0:
            vmax = 0.01
        return vmax, maxVmax

    def getVmax(self, request, context):
        v_max = np.zeros(3)
        max_v_max = np.zeros(3)

        for n, feature in enumerate(request.feature):
            f_v_max = 0
            f_max_v_max = 0
            if feature != '':
                for loomFilePath in request.loomFilePath:
                    l_v_max = 0
                    l_max_v_max = 0
                    loom = self.lfh.get_loom(loom_file_path=loomFilePath)
                    if request.featureType[n] == 'gene':
                        vals, cell_indices = loom.get_gene_expression(
                            gene_symbol=feature,
                            log_transform=request.hasLogTransform,
                            cpm_normalise=request.hasCpmTransform)
                        l_v_max, l_max_v_max = SCope.get_vmax(vals)
                    if request.featureType[n] == 'regulon':
                        vals, cell_indices = loom.get_auc_values(regulon=feature)
                        l_v_max, l_max_v_max = SCope.get_vmax(vals)
                    if request.featureType[n] == 'metric':
                        vals, cell_indices = loom.get_metric(
                            metric_name=feature,
                            log_transform=request.hasLogTransform,
                            cpm_normalise=request.hasCpmTransform)
                        l_v_max, l_max_v_max = SCope.get_vmax(vals)
                    if l_v_max > f_v_max:
                        f_v_max = l_v_max
                if l_max_v_max > f_max_v_max:
                    f_max_v_max = l_max_v_max
            v_max[n] = f_v_max
            max_v_max[n] = f_max_v_max
        return s_pb2.VmaxReply(vmax=v_max, maxVmax=max_v_max)

    def getCellColorByFeatures(self, request, context):
        start_time = time.time()
        try:
            loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        except ValueError:
            return

        cell_color_by_features = ccbf.CellColorByFeatures(loom=loom)

        for n, feature in enumerate(request.feature):
            if request.featureType[n] == 'gene':
                cell_color_by_features.setGeneFeature(request=request, feature=feature, n=n)
            elif request.featureType[n] == 'regulon':
                cell_color_by_features.setRegulonFeature(request=request, feature=feature, n=n)
            elif request.featureType[n] == 'annotation':
                cell_color_by_features.setAnnotationFeature(feature=feature)
                return cell_color_by_features.getReply()
            elif request.featureType[n] == 'metric':
                cell_color_by_features.setMetricFeature(request=request, feature=feature, n=n)
            elif request.featureType[n].startswith('Clustering: '):
                cell_color_by_features.setClusteringFeature(request=request, feature=feature, n=n)
                if(cell_color_by_features.hasReply()):
                    return cell_color_by_features.getReply()
            else:
                cell_color_by_features.addEmptyFeature()

        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        return s_pb2.CellColorByFeaturesReply(color=None,
                                              compressedColor=cell_color_by_features.get_compressed_hex_vec(),
                                              hasAddCompressionLayer=True,
                                              vmax=cell_color_by_features.get_v_max(),
                                              maxVmax=cell_color_by_features.get_max_v_max(),
                                              cellIndices=cell_color_by_features.get_cell_indices())

    def getCellAUCValuesByFeatures(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        vals, cellIndices = loom.get_auc_values(regulon=request.feature[0])
        return s_pb2.CellAUCValuesByFeaturesReply(value=vals)

    def getCellMetaData(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        cell_indices = request.cellIndices
        if len(cell_indices) == 0:
            cell_indices = list(range(loom.get_nb_cells()))

        cell_clusters = []
        for clustering_id in request.clusterings:
            if clustering_id != '':
                cell_clusters.append(loom.get_clustering_by_id(clustering_id=clustering_id)[cell_indices])
        gene_exp = []
        for gene in request.selectedGenes:
            if gene != '':
                vals, _ = loom.get_gene_expression(gene_symbol=gene,
                                                   log_transform=request.hasLogTransform,
                                                   cpm_normalise=request.hasCpmTransform)
                gene_exp.append(vals[cell_indices])
        auc_vals = []
        for regulon in request.selectedRegulons:
            if regulon != '':
                vals, _ = gene_exp.append(loom.get_auc_values(regulon=regulon))
                gene_exp.append(vals[[cell_indices]])
        annotations = []
        for anno in request.annotations:
            if anno != '':
                annotations.append(loom.get_ca_attr_by_name(name=anno)[cell_indices].astype(str))

        return s_pb2.CellMetaDataReply(clusterIDs=[s_pb2.CellClusters(clusters=x) for x in cell_clusters],
                                       geneExpression=[s_pb2.FeatureValues(features=x) for x in gene_exp],
                                       aucValues=[s_pb2.FeatureValues(features=x) for x in gene_exp],
                                       annotations=[s_pb2.CellAnnotations(annotations=x) for x in annotations])

    def getFeatures(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        f = self.get_features(loom=loom, query=request.query)
        return s_pb2.FeatureReply(feature=f['feature'], featureType=f['featureType'], featureDescription=f['featureDescription'])

    def getCoordinates(self, request, context):
        # request content
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        c = loom.get_coordinates(coordinatesID=request.coordinatesID,
                                 annotation=request.annotation,
                                 logic=request.logic)
        return s_pb2.CoordinatesReply(x=c["x"], y=c["y"], cellIndices=c["cellIndices"])

    def getRegulonMetaData(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        regulon_genes = loom.get_regulon_genes(regulon=request.regulon)

        if len(regulon_genes) == 0:
            print("Something is wrong in the loom file: no regulon found!")

        meta_data = loom.get_meta_data()
        for regulon in meta_data['regulonThresholds']:
            if regulon['regulon'] == request.regulon:
                autoThresholds = []
                for threshold in regulon['allThresholds'].keys():
                    autoThresholds.append({"name": threshold, "threshold": regulon['allThresholds'][threshold]})
                defaultThreshold = regulon['defaultThresholdName']
                motifName = os.path.basename(regulon['motifData'])
                break

        regulon = {"genes": regulon_genes,
                   "autoThresholds": autoThresholds,
                   "defaultThreshold": defaultThreshold,
                   "motifName": motifName
                   }

        return s_pb2.RegulonMetaDataReply(regulonMeta=regulon)

    def getMarkerGenes(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        # Check if cluster markers for the given clustering are present in the loom
        if not loom.has_cluster_markers(clustering_id=request.clusteringID):
            print("No markers for clustering {0} present in active loom.".format(request.clusteringID))
            return (s_pb2.MarkerGenesReply(genes=[], metrics=[]))

        genes = loom.get_cluster_marker_genes(clustering_id=request.clusteringID, cluster_id=request.clusterID)
        # Filter the MD clusterings by ID
        md_clustering = loom.get_meta_data_clustering_by_id(id=request.clusteringID)
        cluster_marker_metrics = None

        if "clusterMarkerMetrics" in md_clustering.keys():
            md_cmm = md_clustering["clusterMarkerMetrics"]
            def create_cluster_marker_metric(metric):
                cluster_marker_metrics = loom.get_cluster_marker_metrics(clustering_id=request.clusteringID, cluster_id=request.clusterID, metric_accessor=metric["accessor"])
                return s_pb2.MarkerGenesMetric(accessor=metric["accessor"],
                                               name=metric["name"],
                                               description=metric["description"],
                                               values=cluster_marker_metrics)

            cluster_marker_metrics = list(map(create_cluster_marker_metric, md_cmm))

        return (s_pb2.MarkerGenesReply(genes=genes, metrics=cluster_marker_metrics))

    def getMyGeneSets(self, request, context):
        userDir = dfh.DataFileHandler.get_data_dir_path_by_file_type('GeneSet', UUID=request.UUID)
        if not os.path.isdir(userDir):
            for i in ['Loom', 'GeneSet', 'LoomAUCellRankings']:
                os.mkdir(os.path.join(self.dfh.get_data_dirs()[i]['path'], request.UUID))

        geneSetsToProcess = sorted(self.dfh.get_gobal_sets()) + sorted([os.path.join(request.UUID, x) for x in os.listdir(userDir)])
        gene_sets = [s_pb2.MyGeneSet(geneSetFilePath=f, geneSetDisplayName=os.path.splitext(os.path.basename(f))[0]) for f in geneSetsToProcess]
        return s_pb2.MyGeneSetsReply(myGeneSets=gene_sets)

    def getMyLooms(self, request, context):
        my_looms = []
        userDir = dfh.DataFileHandler.get_data_dir_path_by_file_type('Loom', UUID=request.UUID)
        if not os.path.isdir(userDir):
            for i in ['Loom', 'GeneSet', 'LoomAUCellRankings']:
                os.mkdir(os.path.join(self.dfh.get_data_dirs()[i]['path'], request.UUID))

        self.update_global_data()

        loomsToProcess = sorted(self.lfh.get_global_looms()) + sorted([os.path.join(request.UUID, x) for x in os.listdir(userDir)])

        for f in loomsToProcess:
            if f.endswith('.loom'):
                with open(self.lfh.get_loom_absolute_file_path(f), 'r') as fh:
                    loomSize = os.fstat(fh.fileno())[6]
                loom = self.lfh.get_loom(loom_file_path=f)
                if loom is None:
                    continue
                file_meta = loom.get_file_metadata()
                if not file_meta['hasGlobalMeta']:
                    try:
                        loom.generate_meta_data()
                    except Exception as e:
                        print(e)

                try:
                    L1 = loom.get_global_attribute_by_name(name="SCopeTreeL1")
                    L2 = loom.get_global_attribute_by_name(name="SCopeTreeL2")
                    L3 = loom.get_global_attribute_by_name(name="SCopeTreeL3")
                except AttributeError:
                    L1 = 'Uncategorized'
                    L2 = L3 = ''
                my_looms.append(s_pb2.MyLoom(loomFilePath=f,
                                             loomDisplayName=os.path.splitext(os.path.basename(f))[0],
                                             loomSize=loomSize,
                                             cellMetaData=s_pb2.CellMetaData(annotations=loom.get_meta_data_by_key(key="annotations"),
                                                                             embeddings=loom.get_meta_data_by_key(key="embeddings"),
                                                                             clusterings=loom.get_meta_data_by_key(key="clusterings")),
                                             fileMetaData=file_meta,
                                             loomHeierarchy=s_pb2.LoomHeierarchy(L1=L1,
                                                                                 L2=L2,
                                                                                 L3=L3)
                                             )
                                )
        self.dfh.update_UUID_db()

        return s_pb2.MyLoomsReply(myLooms=my_looms)

    def getUUID(self, request, context):
        if SCope.app_mode:
            with open(os.path.join(self.dfh.get_config_dir(), 'Permanent_Session_IDs.txt'), 'r') as fh:
                newUUID = fh.readline().rstrip('\n')
        else:
            newUUID = str(uuid.uuid4())
        if newUUID not in self.dfh.get_current_UUIDs().keys():
            self.dfh.get_uuid_log().write("{0} :: {1} :: New UUID ({2}) assigned.\n".format(time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime()), request.ip, newUUID))
            self.dfh.get_uuid_log().flush()
            self.dfh.get_current_UUIDs()[newUUID] = time.time()
        return s_pb2.UUIDReply(UUID=newUUID)

    def getRemainingUUIDTime(self, request, context):  # TODO: his function will be called a lot more often, we should reduce what it does.
        curUUIDSet = set(list(self.dfh.get_current_UUIDs().keys()))
        for uid in curUUIDSet:
            timeRemaining = int(dfh._UUID_TIMEOUT - (time.time() - self.dfh.get_current_UUIDs()[uid]))
            if timeRemaining < 0:
                print('Removing UUID: {0}'.format(uid))
                del(self.dfh.get_current_UUIDs()[uid])
                for i in ['Loom', 'GeneSet', 'LoomAUCellRankings']:
                    if os.path.exists(os.path.join(self.dfh.get_data_dirs()[i]['path'], uid)):
                        shutil.rmtree(os.path.join(self.dfh.get_data_dirs()[i]['path'], uid))
        uid = request.UUID
        if uid in self.dfh.get_current_UUIDs():
            startTime = self.dfh.get_current_UUIDs()[uid]
            timeRemaining = int(dfh._UUID_TIMEOUT - (time.time() - startTime))
            self.dfh.get_uuid_log().write("{0} :: {1} :: Old UUID ({2}) connected :: Time Remaining - {3}.\n".format(time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime()), request.ip, uid, timeRemaining))
            self.dfh.get_uuid_log().flush()
        else:
            try:
                uuid.UUID(uid)
            except (KeyError, AttributeError):
                uid = str(uuid.uuid4())
            self.dfh.get_uuid_log().write("{0} :: {1} :: New UUID ({2}) assigned.\n".format(time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime()), request.ip, uid))
            self.dfh.get_uuid_log().flush()
            self.dfh.get_current_UUIDs()[uid] = time.time()
            timeRemaining = int(dfh._UUID_TIMEOUT)

        self.dfh.active_session_check()
        if request.mouseEvents >= Constant._MOUSE_EVENTS_THRESHOLD:
            self.dfh.reset_active_session_timeout(uid)

        sessionsLimitReached = False

        if len(self.dfh.get_active_sessions().keys()) >= Constant._ACTIVE_SESSIONS_LIMIT and uid not in self.dfh.get_permanent_UUIDs() and uid not in self.dfh.get_active_sessions().keys():
            sessionsLimitReached = True

        if uid not in self.dfh.get_active_sessions().keys() and not sessionsLimitReached:
            self.dfh.reset_active_session_timeout(uid)
        return s_pb2.RemainingUUIDTimeReply(UUID=uid, timeRemaining=timeRemaining, sessionsLimitReached=sessionsLimitReached)

    def translateLassoSelection(self, request, context):
        src_loom = self.lfh.get_loom(loom_file_path=request.srcLoomFilePath)
        dest_loom = self.lfh.get_loom(loom_file_path=request.destLoomFilePath)
        src_cell_ids = [src_loom.get_cell_ids()[i] for i in request.cellIndices]
        src_fast_index = set(src_cell_ids)
        dest_mask = [x in src_fast_index for x in dest_loom.get_cell_ids()]
        dest_cell_indices = list(compress(range(len(dest_mask)), dest_mask))
        return s_pb2.TranslateLassoSelectionReply(cellIndices=dest_cell_indices)

    def getCellIDs(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        cell_ids = loom.get_cell_ids()
        slctd_cell_ids = [cell_ids[i] for i in request.cellIndices]
        return s_pb2.CellIDsReply(cellIds=slctd_cell_ids)

    def deleteUserFile(self, request, context):
        basename = os.path.basename(request.filePath)
        finalPath = os.path.join(self.dfh.get_data_dirs()[request.fileType]['path'], request.UUID, basename)
        if os.path.isfile(finalPath) and (basename.endswith('.loom') or basename.endswith('.txt')):
            os.remove(finalPath)
            success = True
        else:
            success = False

        return s_pb2.DeleteUserFileReply(deletedSuccessfully=success)
    
    def downloadSubLoom(self, request, context):
        start_time = time.time()

        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        loom_connection = loom.get_connection()
        meta_data = loom.get_meta_data()

        file_name = request.loomFilePath
        # Check if not a public loom file
        if '/' in request.loomFilePath:
            l = request.loomFilePath.split("/")
            file_name = l[1].split(".")[0]

        if(request.featureType == "clusterings"):
            a = list(filter(lambda x : x['name'] == request.featureName, meta_data["clusterings"]))
            b = list(filter(lambda x : x['description'] == request.featureValue, a[0]['clusters']))[0]
            cells = loom_connection.ca["Clusterings"][str(a[0]['id'])] == b['id']
            print("Number of cells in {0}: {1}".format(request.featureValue, np.sum(cells)))
            sub_loom_file_name = file_name +"_Sub_"+ request.featureValue.replace(" ", "_").replace("/","_")
            sub_loom_file_path = os.path.join(self.dfh.get_data_dirs()['Loom']['path'], "tmp" , sub_loom_file_name +".loom")
            # Check if the file already exists
            if os.path.exists(path=sub_loom_file_path):
                os.remove(path=sub_loom_file_path)
            # Create new file attributes
            sub_loom_file_attrs = dict()
            sub_loom_file_attrs["title"] = sub_loom_file_name
            sub_loom_file_attrs['CreationDate'] = timestamp()
            sub_loom_file_attrs["LOOM_SPEC_VERSION"] = _version.__version__
            sub_loom_file_attrs["note"] = "This loom is a subset of {0} loom file".format(Loom.clean_file_attr(file_attr=loom_connection.attrs["title"]))
            sub_loom_file_attrs["MetaData"] = Loom.clean_file_attr(file_attr=loom_connection.attrs["MetaData"])
            # - Use scan to subset cells (much faster than naive subsetting): avoid to load everything into memory
            # - Loompy bug: loompy.create_append works but generate a file much bigger than its parent
            #      So prepare all the data and create the loom afterwards
            print("Subsetting {0} cluster from the active .loom...".format(request.featureValue))
            sub_matrix = None
            sub_selection = None
            for (_, selection, _) in loom_connection.scan(items=cells, axis=1):
                if sub_matrix is None:
                    sub_matrix = loom_connection[:, selection]
                    sub_selection = selection
                else:
                    sub_matrix = np.concatenate((sub_matrix, loom_connection[:, selection]), axis=1)
                    sub_selection = np.concatenate((sub_selection, selection), axis=0)
                # Send the progress
                processed = len(sub_selection)/sum(cells)
                yield s_pb2.DownloadSubLoomReply(loomFilePath=""
                                               , loomFileSize=0
                                               , progress=s_pb2.Progress(value=processed, status="Sub Loom Created!")
                                               , isDone=False)
            print("Creating {0} sub .loom...".format(request.featureValue))
            lp.create(sub_loom_file_path, sub_matrix, row_attrs=loom_connection.ra, col_attrs=loom_connection.ca[sub_selection], file_attrs=sub_loom_file_attrs)
            with open(sub_loom_file_path, 'r') as fh:
                loom_file_size = os.fstat(fh.fileno())[6]
            print("Done!")
            print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        else:
            print("This feature is currently not implemented.")
        yield s_pb2.DownloadSubLoomReply(loomFilePath=sub_loom_file_path
                                       , loomFileSize=loom_file_size
                                       , progress=s_pb2.Progress(value=1.0, status="Sub Loom Created!")
                                       , isDone=True)

    # Gene set enrichment
    #
    # Threaded makes it slower because of GIL
    #
    def doGeneSetEnrichment(self, request, context):
        gene_set_file_path = os.path.join(self.dfh.get_gene_sets_dir(), request.geneSetFilePath)
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        gse = _gse.GeneSetEnrichment(scope=self,
                                method="AUCell",
                                loom=loom,
                                gene_set_file_path=gene_set_file_path,
                                annotation='')

        # Running AUCell...
        yield gse.update_state(step=-1, status_code=200, status_message="Running AUCell...", values=None)
        time.sleep(1)

        # Reading gene set...
        yield gse.update_state(step=0, status_code=200, status_message="Reading the gene set...", values=None)
        with open(gse.gene_set_file_path, 'r') as f:
            # Skip first line because it contains the name of the signature
            gs = GeneSignature(name='Gene Signature #1',
                               gene2weight=[line.strip() for idx, line in enumerate(f) if idx > 0])
        time.sleep(1)

        if not gse.has_AUCell_rankings():
            # Creating the matrix as DataFrame...
            yield gse.update_state(step=1, status_code=200, status_message="Creating the matrix...", values=None)
            loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
            dgem = np.transpose(loom.get_connection()[:, :])
            ex_mtx = pd.DataFrame(data=dgem,
                                  index=loom.get_ca_attr_by_name("CellID"),
                                  columns=loom.get_genes())
            # Creating the rankings...
            start_time = time.time()
            yield gse.update_state(step=2.1, status_code=200, status_message="Creating the rankings...", values=None)
            rnk_mtx = create_rankings(ex_mtx=ex_mtx)
            # Saving the rankings...
            yield gse.update_state(step=2.2, status_code=200, status_message="Saving the rankings...", values=None)
            lp.create(gse.get_AUCell_ranking_filepath(), rnk_mtx.as_matrix(), {"CellID": loom.get_cell_ids()}, {"Gene": loom.get_genes()})
            print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        else:
            # Load the rankings...
            yield gse.update_state(step=2, status_code=200, status_message="Rankings exists: loading...", values=None)
            rnk_loom = self.lfh.get_loom_connection(gse.get_AUCell_ranking_filepath())
            rnk_mtx = pd.DataFrame(data=rnk_loom[:, :],
                                   index=rnk_loom.ra.CellID,
                                   columns=rnk_loom.ca.Gene)

        # Calculating AUCell enrichment...
        start_time = time.time()
        yield gse.update_state(step=3, status_code=200, status_message="Calculating AUCell enrichment...", values=None)
        aucs = enrichment(rnk_mtx, gs).loc[:, "AUC"].values

        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        yield gse.update_state(step=4, status_code=200, status_message=gse.get_method() + " enrichment done!", values=aucs)

    def loomUploaded(self, request, content):
        uploadedLooms[request.UUID].add(request.filename)
        return s_pb2.LoomUploadedReply()


def serve(run_event, dev_env=False, port=50052, app_mode=False):
    SCope.dev_env = dev_env
    SCope.app_mode = app_mode
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    scope = SCope()
    s_pb2_grpc.add_MainServicer_to_server(scope, server)
    server.add_insecure_port('[::]:{0}'.format(port))
    # print('Starting GServer on port {0}...'.format(port))
    server.start()
    # Let the main process know that GServer has started.
    su.send_msg("GServer", "SIGSTART")

    while run_event.is_set():
        time.sleep(0.1)

    # Write UUIDs to file here
    scope.dfh.get_uuid_log().close()
    scope.dfh.update_UUID_db()
    server.stop(0)


if __name__ == '__main__':
    run_event = threading.Event()
    run_event.set()
    serve(run_event=run_event)
