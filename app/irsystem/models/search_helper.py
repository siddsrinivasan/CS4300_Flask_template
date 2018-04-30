import numpy as np
import pandas as pd
from collections import defaultdict
from scipy.sparse.linalg import svds
from sklearn.preprocessing import normalize
from sklearn.feature_extraction.text import TfidfVectorizer




def filter_by_tfidf_score(tups, threshold, max_results):
    filtered = sorted(tups, key=lambda x: x[0], reverse=True)
    if len(filtered) > max_results:
        return filtered[:max_results]
    return filtered


def closest_docs(index_in, docs_compressed, total_text_to_ix_or_id, max_return=5, min_thresh=.4):
    sims = docs_compressed.dot(docs_compressed[index_in,:])
    asort = np.argsort(-sims)[:max_return+1]
    docs = [(total_text_to_ix_or_id[i],sims[i]/sims[asort[0]], i) \
            for i in asort[1:] if sims[i] > min_thresh]
    return docs



def find_coherent_set(df, red_text, reuters_ids, reddit_ixs):
    reu_trim = filter_by_tfidf_score(reuters_ids, .3 , 500)
    red_trim_dirty = filter_by_tfidf_score(reddit_ixs, .3 , 100)
    red_trim = [rt for rt in red_trim_dirty if len(red_text[rt[1]]) > 4]

    red_score, red_id = map(list,zip(*red_trim))
    reu_score, reu_id = map(list,zip(*reu_trim))

    total_text = [red_text[t] for t in red_id] + \
                    list(df[df['id'].isin(reu_id)]['headline'])

    if len(total_text) < 5:
        return reuters_ids, reddit_ixs

    mat_ix_to_total_text = {}
    total_text_to_ix_or_id = {}
    n_red_articles = len(red_id)
    for ix, txt in enumerate(total_text):
        mat_ix_to_total_text[ix] = txt
        if ix < n_red_articles:
            total_text_to_ix_or_id[ix] = red_id[ix]
        else:
            total_text_to_ix_or_id[ix] = reu_id[ix-n_red_articles]

    vectorizer = TfidfVectorizer(stop_words = 'english', min_df = 3)
    tfidf_mat = vectorizer.fit_transform(total_text).transpose()

    words_compressed, _, docs_compressed = svds(tfidf_mat, k=40)
    docs_compressed = docs_compressed.transpose()
    docs_compressed = normalize(docs_compressed, axis = 1)

    relevant_set = defaultdict(int)
    frontier_set = set([0,1,2])
    explored_set = set()

    while(len(frontier_set) > 0):
        print(frontier_set)
        new_doc_ix = frontier_set.pop()
        explored_set.add(new_doc_ix)
        close_docs = closest_docs(new_doc_ix, docs_compressed, total_text_to_ix_or_id)
        for d, score, ix in close_docs:
            relevant_set[d] += score
            if ix not in explored_set:
                frontier_set.add(ix)

    rel_docs = list(relevant_set.items())

    new_reuters_ids = []
    new_reddit_ixs = []

    for key, score in rel_docs:
        if str(key) == key:
            new_reuters_ids.append((score, key))
        else:
            new_reddit_ixs.append((score, key))

    return new_reuters_ids, new_reddit_ixs