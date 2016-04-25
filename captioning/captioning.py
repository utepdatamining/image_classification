import pickle

import lasagne
import numpy as np
import skimage.transform
import theano
import theano.tensor as T
from lasagne.utils import floatX

from models import googlenet

# Build the model and select layers we need - the features are taken from the final network layer, before the softmax nonlinearity.
cnn_layers = googlenet.build_model()
cnn_input_var = cnn_layers['input'].input_var
cnn_feature_layer = cnn_layers['loss3/classifier']
cnn_output_layer = cnn_layers['prob']

get_cnn_features = theano.function([cnn_input_var], lasagne.layers.get_output(cnn_feature_layer))

# Load the pretrained weights into the network
model_param_values = \
    pickle.load(open(r'/home/rcamachobarranco/datasets/googlenet.pkl', mode='rb'))[
        'param values']
lasagne.layers.set_all_param_values(cnn_output_layer, model_param_values)

# The images need some preprocessing before they can be fed to the CNN

MEAN_VALUES = np.array([104, 117, 123]).reshape((3, 1, 1))


def prep_image(im):
    if len(im.shape) == 2:
        im = im[:, :, np.newaxis]
        im = np.repeat(im, 3, axis=2)
    # Resize so smallest dim = 224, preserving aspect ratio
    h, w, _ = im.shape
    if h < w:
        im = skimage.transform.resize(im, (224, w * 224 / h), preserve_range=True)
    else:
        im = skimage.transform.resize(im, (h * 224 / w, 224), preserve_range=True)

    # Central crop to 224x224
    h, w, _ = im.shape
    im = im[h // 2 - 112:h // 2 + 112, w // 2 - 112:w // 2 + 112]

    # Shuffle axes to c01
    im = np.swapaxes(np.swapaxes(im, 1, 2), 0, 1)

    # Convert to BGR
    im = im[::-1, :, :]

    im = im - MEAN_VALUES
    return floatX(im[np.newaxis])


SEQUENCE_LENGTH = 32
MAX_SENTENCE_LENGTH = SEQUENCE_LENGTH - 3  # 1 for image, 1 for start token, 1 for end token
BATCH_SIZE = 1
CNN_FEATURE_SIZE = 1000
EMBEDDING_SIZE = 256

d = pickle.load(open(r'/home/rcamachobarranco/datasets/lstm_yelp_trained.pkl', mode='rb'))
vocab = d['vocab']
word_to_index = d['word_to_index']
index_to_word = d['index_to_word']

l_input_sentence = lasagne.layers.InputLayer((BATCH_SIZE, SEQUENCE_LENGTH - 1))
l_sentence_embedding = lasagne.layers.EmbeddingLayer(l_input_sentence,
                                                     input_size=len(vocab),
                                                     output_size=EMBEDDING_SIZE,
                                                     )

l_input_cnn = lasagne.layers.InputLayer((BATCH_SIZE, CNN_FEATURE_SIZE))
l_cnn_embedding = lasagne.layers.DenseLayer(l_input_cnn, num_units=EMBEDDING_SIZE,
                                            nonlinearity=lasagne.nonlinearities.identity)

l_cnn_embedding = lasagne.layers.ReshapeLayer(l_cnn_embedding, ([0], 1, [1]))

l_rnn_input = lasagne.layers.ConcatLayer([l_cnn_embedding, l_sentence_embedding])
l_dropout_input = lasagne.layers.DropoutLayer(l_rnn_input, p=0.5)
l_lstm = lasagne.layers.LSTMLayer(l_dropout_input,
                                  num_units=EMBEDDING_SIZE,
                                  unroll_scan=True,
                                  grad_clipping=5.)
l_dropout_output = lasagne.layers.DropoutLayer(l_lstm, p=0.5)
l_shp = lasagne.layers.ReshapeLayer(l_dropout_output, (-1, EMBEDDING_SIZE))
l_decoder = lasagne.layers.DenseLayer(l_shp, num_units=len(vocab), nonlinearity=lasagne.nonlinearities.softmax)

l_out = lasagne.layers.ReshapeLayer(l_decoder, (BATCH_SIZE, SEQUENCE_LENGTH, len(vocab)))

lasagne.layers.set_all_param_values(l_out, d['param values'])

x_cnn_sym = T.matrix()
x_sentence_sym = T.imatrix()

output = lasagne.layers.get_output(l_out, {
    l_input_sentence: x_sentence_sym,
    l_input_cnn: x_cnn_sym
})

f = theano.function([x_cnn_sym, x_sentence_sym], output)


def predict(x_cnn):
    x_sentence = np.zeros((BATCH_SIZE, SEQUENCE_LENGTH - 1), dtype='int32')
    words = []
    i = 0
    while True:
        i += 1
        p0 = f(x_cnn, x_sentence)
        pa = p0.argmax(-1)
        tok = pa[0][i]
        word = index_to_word[tok]
        if word == '#END#' or i >= SEQUENCE_LENGTH - 1:
            return ' '.join(words)
        else:
            x_sentence[0][i] = tok
            if word != '#START#':
                words.append(word)


# Iterate over the dataset and add a field 'cnn features' to each item. This will take quite a while.
def chunks(l, n):
    for i in xrange(0, len(l), n):
        yield l[i:i + n]


for chunk in chunks(dataset, 256):
    cnn_input = floatX(np.zeros((len(chunk), 3, 224, 224)))
    for i, image in enumerate(chunk):
        fn = r'/home/rcamachobarranco/datasets/caption_dataset/{}/{}'.format(image['filepath'], image['filename'])
        try:
            im = plt.imread(fn)
            cnn_input[i] = prep_image(im)
        except IOError:
            continue
    features = get_cnn_features(cnn_input)
    for i, image in enumerate(chunk):
        image['cnn features'] = predict(features[i]

# Save the final product
pickle.dump(dataset, open('/home/rcamachobarranco/datasets/caption_dataset/image_caption_with_cnn_features.pkl', 'w'),
            protocol=pickle.HIGHEST_PROTOCOL)
