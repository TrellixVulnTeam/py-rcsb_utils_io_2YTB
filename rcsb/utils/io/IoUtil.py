##
# File: IoUtil.py
#
# Updates:
#   2-Feb-2018  jdw add default return values for deserialize ops
#   3-Feb-2018  jdw pickle -> pickle  - make default return {} if not specified
#  14-Feb-2018  jdw add fix for the new location of XmlToObj module
#  20-May-2018  jdw move to this module
#   3-Jun-2018  jdw add serializeMmCif/deserializeMmCif
#   4-Jun-2018  jdw overhaul api - provide two public methods.
#   4-Jun-2018  jdw add format for dictionaries which require special parsing
#  15-Jun-2018  jdw add textDump (pretty printer) serialization method -
#  28-Sep-2018  jdw add helper class for serializing python date/datetime types
#   8-Oct-2018  jdw add convenience function to test for file existence
#  11-Oct-2018  jdw make encoding utf-8 for lists
#  13-Oct-2018  jdw add Py27 support for explicit encoding using io.open.
#  26-Oct-2018  jdw add additonal JSON encodings for yaml data types
#  25-Nov-2018  jdw add support for FASTA format sequence files
#  30-Nov-2018  jdw add support CSV file formats
#  11-Dec-2018  jdw add comment filtering on input for CSV files
#   5-Feb-2019  jdw add support for gzip compression as part of serializing mmCIF files.
#   6-Feb-2019  jdw add vrpt-xml-to-cif option and supporting method __deserializeVrptToCif()
#  24-Mar-2019  jdw suppress error message on missing validation report file.
#  25-Mar-2019  jdw expose comment processing for csv/tdd files as keyword argument
#   3-Apr-2019  jdw add comment option and compression handling to __deserializeList()
#  11-Jul-2019  jdw add explicit py2 safe file decompression to avoid encoding problems.
#
#
##

__docformat__ = "restructuredtext en"
__author__ = "John Westbrook"
__email__ = "jwest@rcsb.rutgers.edu"
__license__ = "Apache 2.0"

import bz2
import csv
import datetime
import gzip
import io
import json
import logging
import os
import pickle
import pprint
import random
import shutil
import string
import sys
import tempfile
import zipfile

import ruamel.yaml
from mmcif.io.IoAdapterPy import IoAdapterPy
from rcsb.utils.io.FastaUtil import FastaUtil
from rcsb.utils.validation.ValidationReportReader import ValidationReportReader

try:
    from mmcif.io.IoAdapterCore import IoAdapterCore as IoAdapter  # pylint: disable=ungrouped-imports
except Exception:
    from mmcif.io.IoAdapterPy import IoAdapterPy as IoAdapter  # pylint: disable=reimported,ungrouped-imports


logger = logging.getLogger(__name__)


def uncommentFilter(csvfile):
    for row in csvfile:
        raw = row.split("#")[0].strip()
        if raw:
            yield raw


class JsonTypeEncoder(json.JSONEncoder):
    """ Helper class to handle serializing date and time objects
    """

    # pylint: disable=method-hidden,protected-access
    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()

        if isinstance(o, datetime.date):
            return o.isoformat()

        if isinstance(o, ruamel.yaml.comments.CommentedMap):
            return o._od

        if isinstance(o, ruamel.yaml.comments.CommentedSeq):
            return o._lst

        return json.JSONEncoder.default(self, o)


class IoUtil(object):
    def __init__(self):
        pass

    def serialize(self, filePath, myObj, fmt="pickle", **kwargs):
        """Public method to serialize format appropriate objects

        Args:
            filePath (str): local file path'
            myObj (object): format appropriate object to be serialized
            format (str, optional): one of ['mmcif', mmcif-dict', json', 'list', 'text-dump', pickle' (default)]
            **kwargs: additional keyword arguments passed to worker methods -

        Returns:
            bool: status of serialization operation; true for success or false otherwise

        """
        ret = False
        fmt = str(fmt).lower()
        if fmt in ["mmcif"]:
            ret = self.__serializeMmCif(filePath, myObj, **kwargs)
        elif fmt in ["json"]:
            ret = self.__serializeJson(filePath, myObj, **kwargs)
        elif fmt in ["pickle"]:
            ret = self.__serializePickle(filePath, myObj, **kwargs)
        elif fmt in ["list"]:
            ret = self.__serializeList(filePath, myObj, enforceAscii=True, **kwargs)
        elif fmt in ["mmcif-dict"]:
            ret = self.__serializeMmCifDict(filePath, myObj, **kwargs)
        elif fmt in ["text-dump"]:
            ret = self.__textDump(filePath, myObj, **kwargs)
        elif fmt in ["fasta"]:
            ret = self.__serializeFasta(filePath, myObj, **kwargs)
        elif fmt in ["csv"]:
            ret = self.__serializeCsv(filePath, myObj, **kwargs)
        else:
            pass

        return ret

    def deserialize(self, filePath, fmt="pickle", **kwargs):
        """Public method to deserialize objects in supported formats.

        Args:
            filePath (str): local file path
            format (str, optional): one of ['mmcif', 'json', 'list', ..., 'pickle' (default)]
            **kwargs:  additional keyword arguments passed to worker methods -

        Returns:
            object: deserialized object data

        """
        fmt = str(fmt).lower()
        if fmt in ["mmcif"]:
            ret = self.__deserializeMmCif(filePath, **kwargs)  # type: ignore
        elif fmt in ["json"]:
            ret = self.__deserializeJson(filePath, **kwargs)  # type: ignore
        elif fmt in ["pickle"]:
            ret = self.__deserializePickle(filePath, **kwargs)  # type: ignore
        elif fmt in ["list"]:
            ret = self.__deserializeList(filePath, enforceAscii=True, **kwargs)  # type: ignore
        elif fmt in ["mmcif-dict"]:
            ret = self.__deserializeMmCifDict(filePath, **kwargs)  # type: ignore
        elif fmt in ["fasta"]:
            ret = self.__deserializeFasta(filePath, **kwargs)  # type: ignore
        elif fmt in ["vrpt-xml-to-cif"]:
            ret = self.__deserializeVrptToCif(filePath, **kwargs)  # type: ignore
        elif fmt in ["csv", "tdd"]:
            delimiter = "," if fmt == "csv" else "\t"
            ret = self.__deserializeCsv(filePath, delimiter=delimiter, **kwargs)  # type: ignore
        else:
            ret = None  # type: ignore

        return ret

    def exists(self, filePath, mode=os.R_OK):
        try:
            return os.access(filePath, mode)
        except Exception:
            return False

    def __compress(self, inpPath, outPath, compressType="gzip"):
        try:
            if compressType == "gzip":
                with open(inpPath, "rb") as fIn:
                    with gzip.open(outPath, "wb") as fOut:
                        shutil.copyfileobj(fIn, fOut)
                return True
            else:
                logger.error("Unsupported compressType %r", compressType)
        except Exception as e:
            logger.exception("Compressing file %s failing with %s", inpPath, str(e))
            return False

    def __deserializeFasta(self, filePath, **kwargs):
        try:
            commentStyle = kwargs.get("commentStyle", "uniprot")
            fau = FastaUtil()
            return fau.readFasta(filePath, commentStyle=commentStyle)
        except Exception as e:
            logger.error("Unable to deserialize %r %r ", filePath, str(e))
        return {}

    def __deserializeVrptToCif(self, filePath, **kwargs):
        """ Deserialize XML validation report data file and return as mmcif container list
        """
        try:
            dictMapPath = kwargs.get("dictMapPath", None)
            if not dictMapPath:
                logger.error("Missing dictionary mapping file")
            dictMap = self.__deserializeJson(dictMapPath)
            vrr = ValidationReportReader(dictMap)
            return vrr.toCif(filePath)
        except Exception as e:
            logger.debug("Unable to deserialize %r %r", filePath, str(e))
        return {}

    def __serializeFasta(self, filePath, myObj, **kwargs):
        try:
            maxLineLength = int(kwargs.get("maxLineLength", 70))
            fau = FastaUtil()
            ok = fau.writeFasta(filePath, myObj, maxLineLength=maxLineLength)
            return ok
        except Exception as e:
            logger.error("Unable to serialize FASTA file %r  %r", filePath, str(e))
        return False

    def __textDump(self, filePath, myObj, **kwargs):
        try:
            indent = kwargs.get("indent", 1)
            width = kwargs.get("width", 120)
            sOut = pprint.pformat(myObj, indent=indent, width=width)
            with open(filePath, "w") as ofh:
                ofh.write("\n%s\n" % sOut)
            return True
        except Exception as e:
            logger.error("Unable to dump to %r  %r", filePath, str(e))
        return False

    def __serializePickle(self, filePath, myObj, **kwargs):
        try:
            pickleProtocol = kwargs.get("pickleProtocol", pickle.HIGHEST_PROTOCOL)

            with open(filePath, "wb") as outfile:
                pickle.dump(myObj, outfile, pickleProtocol)
            return True
        except Exception as e:
            logger.error("Unable to serialize %r  %r", filePath, str(e))
        return False

    def __deserializePickle(self, filePath, **kwargs):
        myDefault = kwargs.get("default", {})
        try:
            with open(filePath, "rb") as outfile:
                return pickle.load(outfile)
        except Exception as e:
            logger.warning("Unable to deserialize %r %r", filePath, str(e))
        return myDefault

    def __serializeJson(self, filePath, myObj, **kwargs):
        """ Internal method to serialize the input object as JSON.  An encoding
            helper class is included to handle selected python data types (e.g., datetime)
        """
        indent = kwargs.get("indent", 0)
        try:
            with open(filePath, "w") as outfile:
                json.dump(myObj, outfile, indent=indent, cls=JsonTypeEncoder)
            return True
        except Exception as e:
            logger.error("Unable to serialize %r  %r", filePath, str(e))
        return False

    def __deserializeJson(self, filePath, **kwargs):
        myDefault = kwargs.get("default", {})
        try:
            with open(filePath, "r") as infile:
                return json.load(infile)
        except Exception as e:
            logger.warning("Unable to deserialize %r %r", filePath, str(e))
        return myDefault

    def __deserializeMmCif(self, filePath, **kwargs):
        """
        """
        try:
            containerList = []
            workPath = kwargs.get("workPath", None)
            enforceAscii = kwargs.get("enforceAscii", True)
            raiseExceptions = kwargs.get("raiseExceptions", True)
            useCharRefs = kwargs.get("useCharRefs", True)
            #
            myIo = IoAdapter(raiseExceptions=raiseExceptions, useCharRefs=useCharRefs)
            containerList = myIo.readFile(filePath, enforceAscii=enforceAscii, outDirPath=workPath)  # type: ignore
        except Exception as e:
            logger.error("Failing for %s with %s", filePath, str(e))
        return containerList

    def __serializeMmCif(self, filePath, containerList, **kwargs):
        """
        """
        try:
            ret = False
            workPath = kwargs.get("workPath", None)
            enforceAscii = kwargs.get("enforceAscii", True)
            raiseExceptions = kwargs.get("raiseExceptions", True)
            useCharRefs = kwargs.get("useCharRefs", True)
            #
            myIo = IoAdapter(raiseExceptions=raiseExceptions, useCharRefs=useCharRefs)
            if filePath.endswith(".gz") and workPath:
                rfn = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
                tPath = os.path.join(workPath, rfn)
                ret = myIo.writeFile(tPath, containerList=containerList, enforceAscii=enforceAscii)
                ret = self.__compress(tPath, filePath, compressType="gzip")
            else:
                ret = myIo.writeFile(filePath, containerList=containerList, enforceAscii=enforceAscii)
        except Exception as e:
            logger.error("Failing for %s with %s", filePath, str(e))
        return ret

    def __deserializeMmCifDict(self, filePath, **kwargs):
        """
        """
        try:
            containerList = []
            workPath = kwargs.get("workPath", None)
            enforceAscii = kwargs.get("enforceAscii", True)
            raiseExceptions = kwargs.get("raiseExceptions", True)
            useCharRefs = kwargs.get("useCharRefs", True)
            #
            myIo = IoAdapterPy(raiseExceptions=raiseExceptions, useCharRefs=useCharRefs)
            containerList = myIo.readFile(filePath, enforceAscii=enforceAscii, outDirPath=workPath)
        except Exception as e:
            logger.error("Failing for %s with %s", filePath, str(e))
        return containerList

    def __serializeMmCifDict(self, filePath, containerList, **kwargs):
        """
        """
        try:
            ret = False
            # workPath = kwargs.get('workPath', None)
            enforceAscii = kwargs.get("enforceAscii", True)
            raiseExceptions = kwargs.get("raiseExceptions", True)
            useCharRefs = kwargs.get("useCharRefs", True)
            #
            myIo = IoAdapterPy(raiseExceptions=raiseExceptions, useCharRefs=useCharRefs)
            ret = myIo.writeFile(filePath, containerList=containerList, enforceAscii=enforceAscii)
        except Exception as e:
            logger.error("Failing for %s with %s", filePath, str(e))
        return ret

    def __serializeList(self, filePath, aList, enforceAscii=True, **kwargs):
        """
        """

        try:
            _ = kwargs
            if enforceAscii:
                encoding = "ascii"
            else:
                encoding = "utf-8"
            #
            if sys.version_info[0] > 2:
                with open(filePath, "w") as ofh:
                    if enforceAscii:
                        for st in aList:
                            ofh.write("%s\n" % st.encode("ascii", "xmlcharrefreplace").decode("ascii"))
                    else:
                        for st in aList:
                            ofh.write("%s\n" % st)
            else:
                if enforceAscii:
                    with io.open(filePath, "w", encoding=encoding) as ofh:
                        for st in aList:
                            ofh.write("%s\n" % st.encode("ascii", "xmlcharrefreplace").decode("ascii"))
                else:
                    with open(filePath, "wb") as ofh:
                        for st in aList:
                            ofh.write("%s\n" % st)
            return True
        except Exception as e:
            logger.error("Unable to serialize %r %r", filePath, str(e))
        return False

    def __processList(self, ifh, enforceAscii=True, uncomment=True):
        aList = []
        for line in ifh:
            if enforceAscii:
                pth = line[:-1].encode("ascii", "xmlcharrefreplace").decode("ascii")
            else:
                pth = line[:-1]
            if not pth or (uncomment and pth.startswith("#")):
                continue
            aList.append(pth)
        return aList

    def __deserializeList(self, filePath, enforceAscii=True, encodingErrors="ignore", **kwargs):
        aList = []
        _ = kwargs
        try:
            if filePath[-3:] == ".gz":
                if sys.version_info[0] > 2:
                    with gzip.open(filePath, "rt", encoding="utf-8-sig", errors=encodingErrors) as ifh:
                        aList = self.__processList(ifh, enforceAscii=enforceAscii)
                else:
                    tPath = self.__uncompress(filePath, outputDir=None)
                    # for py2 this commented code is problematic for non-ascii data
                    # with gzip.open(filePath, "rb") as ifh:
                    #    aList = self.__processList(ifh, enforceAscii=enforceAscii)
                    with io.open(tPath, encoding="utf-8-sig", errors="ignore") as ifh:
                        aList = self.__processList(ifh, enforceAscii=enforceAscii)
            else:
                with io.open(filePath, encoding="utf-8-sig", errors="ignore") as ifh:
                    aList = self.__processList(ifh, enforceAscii=enforceAscii)
        except Exception as e:
            logger.error("Unable to deserialize %r %s", filePath, str(e))
        #
        logger.debug("Reading list length %d", len(aList))
        return aList

    def __toAscii(self, inputFilePath, outputFilePath, chunkSize=5000, encodingErrors="ignore"):
        """ Encode input file to Ascii and write this to the target output file.   Handle encoding
            errors according to the input settting ('ignore', 'escape', 'xmlcharrefreplace').
        """
        try:
            chunk = []
            with io.open(inputFilePath, "r", encoding="utf-8") as rIn, io.open(outputFilePath, "w", encoding="ascii") as wOut:
                for line in rIn:
                    # chunk.append(line.encode('ascii', 'xmlcharrefreplace').decode('ascii'))
                    chunk.append(line.encode("ascii", encodingErrors).decode("ascii"))
                    if len(chunk) == chunkSize:
                        wOut.writelines(chunk)
                        chunk = []
                wOut.writelines(chunk)
            return True
        except Exception as e:
            logger.error("Failing text ascii encoding for %s with %s", inputFilePath, str(e))
        #
        return False

    def __csvReader(self, csvFile, rowFormat, delimiter, uncomment=True):
        oL = []

        maxInt = sys.maxsize
        csv.field_size_limit(maxInt)
        if rowFormat == "dict":
            if uncomment:
                reader = csv.DictReader(uncommentFilter(csvFile), delimiter=delimiter)
            else:
                reader = csv.DictReader(csvFile, delimiter=delimiter)
            for rowD in reader:
                oL.append(rowD)
        elif rowFormat == "list":
            if uncomment:
                reader = csv.reader(uncommentFilter(csvFile), delimiter=delimiter)
            else:
                reader = csv.reader(csvFile, delimiter=delimiter)
            for rowL in reader:
                oL.append(rowL)
        return oL

    def __deserializeCsv(self, filePath, delimiter=",", rowFormat="dict", encodingErrors="ignore", uncomment=True, **kwargs):
        oL = []
        encoding = kwargs.get("encoding", "utf-8-sig")
        try:
            if filePath[-3:] == ".gz":
                if sys.version_info[0] > 2:
                    with gzip.open(filePath, "rt", encoding=encoding, errors=encodingErrors) as csvFile:
                        oL = self.__csvReader(csvFile, rowFormat, delimiter, uncomment=uncomment)
                else:
                    # Py2 situation non-ascii encodings is problematic
                    # with gzip.open(filePath, "rb") as csvFile:
                    #    oL = self.__csvReader(csvFile, rowFormat, delimiter)
                    tPath = self.__uncompress(filePath, outputDir=None)
                    with io.open(tPath, newline="", encoding=encoding, errors="ignore") as csvFile:
                        oL = self.__csvReader(csvFile, rowFormat, delimiter, uncomment=uncomment)
            else:
                with io.open(filePath, newline="", encoding=encoding, errors="ignore") as csvFile:
                    oL = self.__csvReader(csvFile, rowFormat, delimiter, uncomment=uncomment)

            return oL
        except Exception as e:
            logger.exception("Unable to deserialize %r %s", filePath, str(e))
        #
        logger.debug("Reading list length %d", len(oL))
        return oL

    def __serializeCsv(self, filePath, rowDictList, fieldNames=None, **kwargs):
        """
        """
        _ = kwargs
        try:
            wD = {}
            ret = False
            fNames = fieldNames if fieldNames else list(rowDictList[0].keys())
            # with io.open(filePath, 'w', newline='') as csvFile:
            with open(filePath, "w") as csvFile:
                writer = csv.DictWriter(csvFile, fieldnames=fNames)
                writer.writeheader()
                for ii, rowDict in enumerate(rowDictList):
                    try:
                        wD = {k: v for k, v in rowDict.items() if k in fNames}
                        writer.writerow(wD)
                    except Exception as e:
                        logger.error("Skipping bad CSV record %d wD %r rowDict %r", ii + 1, wD, rowDict)
                        continue

            ret = True
        except Exception as e:
            logger.error("Failing for %s : %r with %s", filePath, wD, str(e))
        return ret

    def __uncompress(self, inputFilePath, outputDir=None):
        """ Uncompress the input file if the path name has a recognized compression type file extension.

            Return the path of the uncompressed file (in outDir) or the original input file path.

        """
        try:
            outputDir = outputDir if outputDir else tempfile.gettempdir()
            _, fn = os.path.split(inputFilePath)
            bn, _ = os.path.splitext(fn)
            outputFilePath = os.path.join(outputDir, bn)
            if inputFilePath.endswith(".gz"):
                with gzip.open(inputFilePath, mode="rb") as inpF:
                    with io.open(outputFilePath, "wb") as outF:
                        shutil.copyfileobj(inpF, outF)
            elif inputFilePath.endswith(".bz2"):
                with bz2.open(inputFilePath, mode="rb") as inpF:
                    with io.open(outputFilePath, "wb") as outF:
                        shutil.copyfileobj(inpF, outF)
            # elif inputFilePath.endswith(".xz"):
            #    with lzma.open(inputFilePath, mode="rb") as inpF:
            #        with io.open(outputFilePath, "wb") as outF:
            #            shutil.copyfileobj(inpF, outF)
            elif inputFilePath.endswith(".zip"):
                with zipfile.ZipFile(inputFilePath, mode="rb") as inpF:
                    with io.open(outputFilePath, "wb") as outF:
                        shutil.copyfileobj(inpF, outF)
            else:
                outputFilePath = inputFilePath

        except Exception as e:
            logger.exception("Failing uncompress for file %s with %s", inputFilePath, str(e))
        logger.debug("Returning file path %r", outputFilePath)
        return outputFilePath

    def __csvEncoder(self, csvData, encoding="utf-8-sig", encodingErrors="ignore"):
        """ Handle encoding issues for gzipped data in Py2. (beware of the BOM chars)

        Args:
            csvData (text lines): uncompressed data from gzip open
            encoding (str, optional): character encoding. Defaults to "utf-8-sig".
            encodingErrors (str, optional): error treatement. Defaults to "ignore".
        """
        for line in csvData:
            yield line.decode("utf-8-sig", errors=encodingErrors).encode(encoding, errors=encodingErrors)
