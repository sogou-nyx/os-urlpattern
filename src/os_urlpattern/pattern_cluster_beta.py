from collections import OrderedDict, Counter

from .compat import itervalues, iteritems
from .definition import DIGIT_AND_ASCII_RULE_SET, BasePatternRule
from .node_viewer import BaseViewer, LengthViewer, MixedViewer, PieceViewer
from .parse_utils import URLMeta, number_rule, wildcard_rule
from .pattern import Pattern
from .piece_pattern_tree import PiecePatternTree
from .utils import Bag


class CBag(Bag):
    def __init__(self):
        super(CBag, self).__init__()
        self._count = 0

    @property
    def count(self):
        return self._count

    def add(self, obj):
        super(CBag, self).add(obj)
        self._count += obj.count

    def set_pattern(self, pattern):
        for obj in self:
            obj.set_pattern(pattern)

    def remove(self, obj):
        if obj in self._objs:
            self._count -= obj.count
            self._objs.remove(obj)


class PatternCluster(object):
    def __init__(self, processor):
        self._processor = processor
        self._min_cluster_num = processor.config.getint(
            'make', 'min_cluster_num')

    def get_processor(self, n):
        processor = self._processor
        while n > 0 and processor is not None:
            processor = processor.pre_level_processor
            n -= 1
        return processor

    @property
    def pre_level_processor(self):
        return self._processor.pre_level_processor

    def as_cluster(self, parsed_piece_counter):
        return False

    def cluster(self):
        pass

    def add(self, obj):
        pass


class PBag(CBag):
    def __init__(self):
        super(PBag, self).__init__()
        self._skip = False
        self._parsed_piece_counter = Counter()

    def incr(self, incr):
        self._count += incr

    @property
    def skip(self):
        return self._skip

    @skip.setter
    def skip(self, skip):
        self._skip = skip

    def add(self, piece_node):
        super(PBag, self).add(piece_node)
        p_node = piece_node.parrent
        self._parsed_piece_counter[p_node.parsed_piece] += piece_node.count

    def remove(self, obj):
        raise NotImplementedError

    @property
    def parsed_piece_counter(self):
        return self._parsed_piece_counter


class PBucket(Bag):
    def __init__(self):
        super(PBucket, self).__init__()
        self._objs = {}

    def add(self, piece_bag):
        piece = piece_bag.pick().piece
        if piece in self._objs:
            raise ValueError('duplicated')
        self._objs[piece] = piece_bag

    def _get(self):
        for obj in itervalues(self._objs):
            return obj

    def get(self, piece):
        return self._objs[piece]

    def __iter__(self):
        return itervalues(self._objs)

    @property
    def count(self):
        return sum([o.count for o in itervalues(self._objs)])


def confused(total, part, threshold):
    if total < threshold:
        return False
    o_part = total - part
    if part >= threshold and o_part >= threshold:
        return True
    return abs(part - o_part) < threshold - 1


class PiecePatternCluster(PatternCluster):
    def __init__(self, processor):
        super(PiecePatternCluster, self).__init__(processor)
        self._piece_bags = {}

    def revise(self, piece_counter):
        for piece, count in iteritems(piece_counter):
            self._piece_bags[piece].incr(0 - count)

    def as_cluster(self, parsed_piece_counter):
        if len(parsed_piece_counter) >= self._min_cluster_num:
            return False
        max_count = 0
        total_count = 0
        for parsed_piece in parsed_piece_counter:
            piece_bag = self._piece_bags[parsed_piece.piece]
            if piece_bag.count > max_count:
                max_count = piece_bag.count
            total_count += piece_bag.count
        return not confused(total_count, max_count, self._min_cluster_num)

    def iter_nodes(self):
        for bag in itervalues(self._piece_bags):
            for node in bag.iter_all():
                yield node

    def add(self, piece_pattern_node):
        piece = piece_pattern_node.piece
        if piece not in self._piece_bags:
            self._piece_bags[piece] = PBag()
        bag = self._piece_bags[piece]
        bag.add(piece_pattern_node)
        if bag.skip or bag.count < self._min_cluster_num:
            return

        p_node = piece_pattern_node.parrent
        if p_node is None or p_node.children_num == 1:
            return

        if p_node.count - piece_pattern_node.count >= self._min_cluster_num:
            bag.skip = True
            return

        for b_node in p_node.iter_children():
            b_piece = b_node.piece
            if b_piece == piece or b_piece not in self._piece_bags:
                continue
            b_bag = self._piece_bags[b_piece]
            if b_bag.count >= self._min_cluster_num:
                b_bag.skip = True
                bag.skip = True
                break

    def _get_forward_cluster(self):
        cluster_cls = LengthPatternCluster
        piece_pattern_node = next(itervalues(self._piece_bags)).pick()
        if len(piece_pattern_node.parsed_piece.pieces) > 1:
            cluster_cls = BasePatternCluster
        return self._processor.get_cluster(cluster_cls)

    def cluster(self):
        n = len(self._piece_bags)
        if n == 1:
            return

        forward_cluster = self._get_forward_cluster()

        for piece_bag in itervalues(self._piece_bags):
            if piece_bag.skip \
                    or piece_bag.count < self._min_cluster_num \
                    or not self.get_processor(1).seek_cluster(piece_bag.p_counter):
                forward_cluster.add(piece_bag)
            else:
                self._processor.get_cluster(
                    PiecePatternCluster).revise(piece_bag.p_counter)


class LengthPatternCluster(PatternCluster):
    def __init__(self, processor):
        super(LengthPatternCluster, self).__init__(processor)
        self._length_buckets = {}

    def as_cluster(self, parsed_piece_counter):
        if len(parsed_piece_counter) >= self._min_cluster_num:
            return False
        lengths = [node.parsed_piece.piece_length for node in nodes]
        if len(lengths) >= self._min_cluster_num:
            return False

        max_count = 0
        total_count = 0
        for length in lengths:
            length_bag = self._length_bags[length]
            if length_bag.count > max_count:
                max_count = length_bag.count
            total_count += length_bag.count

        return not confused(total_count, max_count, self._min_cluster_num)

    def add(self, piece_bag):
        piece_length = piece_bag.pick().parsed_piece.piece_length
        if piece_length not in self._length_buckets:
            self._length_buckets[piece_length] = PBucket()
        self._length_buckets[piece_length].add(piece_bag)

    def cluster(self):
        forward_cluster = self._processor.get_cluster(FuzzyPatternCluster)
        for length_bucket in itervalues(self._length_buckets):
            if length_bucket.count < self._min_cluster_num:
                forward_cluster.add(length_bucket)

    def _set_pattern(self, length_bag):
        parsed_piece = length_bag.pick().parsed_piece
        length = parsed_piece.piece_length
        pattern = Pattern(number_rule(parsed_piece.fuzzy_rule, length))
        length_bag.set_pattern(pattern)


class MultiPartPatternCluster(PatternCluster):
    pass


class BasePatternCluster(MultiPartPatternCluster):
    def __init__(self, processor):
        super(BasePatternCluster, self).__init__(processor)

    def add(self, piece_bag):
        pass


class MixedPatternCluster(MultiPartPatternCluster):
    def __init__(self, processor):
        super(MixedPatternCluster, self).__init__(processor)

    def add(self, piece_bag):
        pass


class LastDotSplitFuzzyPatternCluster(MultiPartPatternCluster):
    def __init__(self, processor):
        super(LastDotSplitFuzzyPatternCluster, self).__init__(processor)

    def add(self, piece_bag):
        pass


class FuzzyPatternCluster(PatternCluster):
    def __init__(self, processor):
        super(FuzzyPatternCluster, self).__init__(processor)
        self._cached_bag = CBag()
        self._force_pattern = False
        self._fuzzy_pattern = None
        self._mc_bag = None

    def add(self, bag):
        if self._force_pattern:
            self._set_pattern(bag)
        else:
            self._cached_bag.add(bag)
            if self._mc_bag is None or bag.count > self._mc_bag.count:
                self._mc_bag = bag
            if len(self._cached_bag) >= self._min_cluster_num:
                self._force_pattern = True

    def cluster(self):
        cbc = self._cached_bag.count
        if cbc <= 0:
            return
        mcn = self._min_cluster_num
        mbc = self._mc_bag.count
        if self._force_pattern \
            or (len(self._cached_bag) > 1
                and cbc >= mcn
                and (mbc < mcn
                     or cbc - mbc >= mcn
                     or 2 * mbc - cbc < mcn - 1)):
            self._set_pattern(self._cached_bag)

    def _set_pattern(self, bag):
        if self._fuzzy_pattern is None:
            self._fuzzy_pattern = Pattern(
                wildcard_rule(bag.pick().parsed_piece.fuzzy_rule))
        bag.set_pattern(self._fuzzy_pattern)


class MetaInfo(object):
    def __init__(self, url_meta, current_level):
        self._url_meta = url_meta
        self._current_level = current_level

    @property
    def current_level(self):
        return self._current_level

    @property
    def url_meta(self):
        return self._url_meta

    def is_last_level(self):
        return self.url_meta.depth == self._current_level

    def is_last_path(self):
        return self.url_meta.path_depth == self._current_level

    def next_level_meta_info(self):
        return MetaInfo(self.url_meta, self.current_level + 1)


CLUSTER_CLASSES = [PiecePatternCluster, BasePatternCluster, MixedPatternCluster,
                   LastDotSplitFuzzyPatternCluster, LengthPatternCluster,
                   FuzzyPatternCluster]


class ClusterProcessor(object):
    def __init__(self, config, meta_info, pre_level_processor):
        self._config = config
        self._meta_info = meta_info
        self._pattern_clusters = OrderedDict(
            [(c.__name__, c(self)) for c in CLUSTER_CLASSES])
        self._pre_level_processor = pre_level_processor

    def seek_cluster(self, parsed_piece_counter):
        for c in self._pattern_clusters.itervalues():
            if c.as_cluster(parsed_piece_counter):
                return True

        return False

    def get_cluster(self, cluster_cls):
        return self._pattern_clusters[cluster_cls.__name__]

    @property
    def meta_info(self):
        return self._meta_info

    @property
    def config(self):
        return self._config

    @property
    def pre_level_processor(self):
        return self._pre_level_processor

    def _process(self, ):
        for c in self._pattern_clusters.itervalues():
            c.cluster()

    def process(self):
        self._process()
        if self._meta_info.is_last_level():
            return

        next_level_processors = self._create_next_level_processors()

        for processor in itervalues(next_level_processors):
            processor.process()

    def _create_next_level_processors(self):
        pp_cluster = self.get_cluster(PiecePatternCluster)
        next_level_processors = {}

        for node in pp_cluster.iter_nodes():
            pattern = node.pattern
            if pattern not in next_level_processors:
                next_level_processors[pattern] = self._create_next_level_processor(
                )
            next_level_processor = next_level_processors[pattern]
            next_pp_cluster = next_level_processor.get_cluster(
                PiecePatternCluster)
            for child in node.iter_children():
                next_pp_cluster.add(child)

        return next_level_processors

    def _create_next_level_processor(self):
        return ClusterProcessor(self._config,
                                self._meta_info.next_level_meta_info(),
                                self)


def split(piece_pattern_tree):
    yield


def process(config, url_meta, piece_pattern_tree, **kwargs):
    meta_info = MetaInfo(url_meta, 0)
    processor = ClusterProcessor(config, meta_info, None)
    processor.get_cluster(PiecePatternCluster).add(piece_pattern_tree.root)
    processor.process()


def cluster(config, url_meta, piece_pattern_tree, **kwargs):
    process(config, url_meta, piece_pattern_tree, **kwargs)

    return
    for sub_piece_pattern_tree in split(piece_pattern_tree):
        process(config, url_meta, sub_piece_pattern_tree)
