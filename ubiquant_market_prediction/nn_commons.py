import torch.nn as nn
import torch
import numpy as np


class NNArch(nn.Module):
    def _set_embedding(
        self,
        input_size,
        use_embedding=False,
        embedding_dim_list=None,
        num_embeddings_list=None,
    ):
        self.use_embedding = use_embedding
        if not self.use_embedding:
            return input_size

        assert isinstance(embedding_dim_list, list)
        assert isinstance(num_embeddings_list, list)
        assert len(embedding_dim_list) == len(num_embeddings_list)

        self.embedding_layers = []
        for embedding_dim, num_embeddings in zip(
            embedding_dim_list, num_embeddings_list
        ):
            embedding_layer = nn.Embedding(
                num_embeddings=num_embeddings,
                embedding_dim=embedding_dim,
            )
            self.embedding_layers.append(embedding_layer)
        # update input size based on embedding sizes
        input_size = input_size + sum(embedding_dim_list) - len(embedding_dim_list)
        return input_size

    def _set_attention(self,
        input_size,
        use_attention=False,
        attention_hidden_sizes=[8],
        activation_type="leakyrelu",
    ):
        self.use_attention = use_attention
        if self.use_attention:
            self.attention_layer = []
            prev_size = input_size
            for size in attention_hidden_sizes:
                self.attention_layer.append(nn.Linear(prev_size, size))
                self.attention_layer.append(get_activation(activation_type))
                prev_size = size

            self.attention_layer.append(nn.Linear(prev_size, input_size))
            self.attention_layer.append(nn.Sigmoid())
            self.attention_layer = nn.Sequential(*self.attention_layer)


class MLPArch(NNArch):
    def __init__(
        self,
        input_size,
        hidden_sizes=[32, 16, 8],
        dropout_prob=0.1,
        activation_type="leakyrelu",
        use_attention=False,
        attention_hidden_sizes=[8],
        use_embedding=False,
        embedding_dim_list=None,
        num_embeddings_list=None,
    ):
        super(MLPArch, self).__init__()

        input_size = self._set_embedding(
            input_size,
            use_embedding,
            embedding_dim_list,
            num_embeddings_list,
        )
        self._set_attention(
            input_size,
            use_attention,
            attention_hidden_sizes,
            activation_type,
        )
        # Initialize Regressor
        layers = []
        past_size = input_size
        for size in hidden_sizes:
            layers.append(nn.Linear(past_size, size))
            layers.append(get_activation(activation_type))
            if dropout_prob > 0:
                layers.append(nn.Dropout(dropout_prob))
            past_size = size
        layers.append(nn.Linear(past_size, 1))
        self.regressor = nn.Sequential(*layers)

    def forward(self, x):

        if self.use_embedding:
            embedded_features = []
            for i, embedding_layer in enumerate(self.embedding_layers):
                cat_feat = x[:, i].int()
                emb_feat = embedding_layer(cat_feat)
                embedded_features.append(emb_feat)
            embedded_features = torch.cat(embedded_features, 1)
            x = torch.cat([embedded_features, x[:, len(self.embedding_layers) :]], 1)

        if self.use_attention:
            x = x * self.attention_layer(x)

        return self.regressor(x).squeeze(-1)


class RNNArch(nn.Module):
    """
    Input and output tensors are provided as (batch, seq, feature)
    """
    DEFAULTS = {}

    def __init__(
        self,
        input_size,
        hidden_size=32,
        num_layers=1,
        dropout_prob=0.1,
        activation_type="leakyrelu",
        rnn_type="LSTM",
        use_attention=False,
        attention_hidden_sizes=[8],
        use_embedding=False,
        embedding_dim_list=None,
        num_embeddings_list=None,
    ):
        super(RNNArch, self).__init__()

        self.use_embedding = use_embedding
        if self.use_embedding:
            assert isinstance(embedding_dim_list, list)
            assert isinstance(num_embeddings_list, list)
            assert len(embedding_dim_list) == len(num_embeddings_list)

            self.embedding_layers = []
            for embedding_dim, num_embeddings in zip(
                embedding_dim_list, num_embeddings_list
            ):
                embedding_layer = nn.Embedding(
                    num_embeddings=num_embeddings,
                    embedding_dim=embedding_dim,
                )
                self.embedding_layers.append(embedding_layer)
            # update input size based on embedding sizes
            input_size = input_size + sum(embedding_dim_list) - len(embedding_dim_list)

        self.use_attention = use_attention
        if self.use_attention:
            self.attention_layer = []
            prev_size = input_size
            for size in attention_hidden_sizes:
                self.attention_layer.append(nn.Linear(prev_size, size))
                self.attention_layer.append(get_activation(activation_type))
                prev_size = size

            self.attention_layer.append(nn.Linear(prev_size, input_size))
            self.attention_layer.append(nn.Sigmoid())
            self.attention_layer = nn.Sequential(*self.attention_layer)

        # Initialize RNN
        self.rnn = getattr(nn, rnn_type)(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout_prob,
            batch_first=True,
        )

        # Initialize Regressor
        layers = []
        layers.append(nn.Linear(hidden_size, hidden_size))
        layers.append(get_activation(activation_type))
        if dropout_prob > 0:
            layers.append(nn.Dropout(dropout_prob))
        layers.append(nn.Linear(hidden_size, 1))
        self.regressor = nn.Sequential(*layers)

    def forward(self, x, h_state=None):

        if self.use_embedding:
            embedded_features = []
            for i, embedding_layer in enumerate(self.embedding_layers):
                cat_feat = x[:, :, i].int()
                emb_feat = embedding_layer(cat_feat)
                embedded_features.append(emb_feat)
            embedded_features = torch.cat(embedded_features, 2)
            x = torch.cat([embedded_features, x[:, :, len(self.embedding_layers) :]], 2)

        if self.use_attention:
            x = x * self.attention_layer(x)

        # RNN
        out_rnn, h_state = self.rnn(x, h_state)

        # The following line is doing: N,T,F_hidden --> NT, F_hidden --> N,T,F_out
        N, T, _ = x.shape
        out_reg = self.regressor(out_rnn.reshape([N * T, -1])).reshape([N, T, -1])
        return out_reg.squeeze(-1), h_state


def get_activation(activation_type):
    if activation_type.lower() == "leakyrelu":
        return nn.LeakyReLU(0.02)
    if activation_type.lower() == "silu":
        return nn.SiLU()
    if activation_type.lower() == "mish":
        return nn.Mish()
    raise ValueError(f"Unknown activation type {activation_type}")


def to_numpy(x):
    return x.data.numpy()


def to_tensor(x):
    if type(x) != type(torch.tensor(0)):
        x = torch.tensor(x.astype("float32"))
    return x


class TensorLoader:
    def __init__(self, x, y):
        self.x = x.astype("float32")
        self.y = y.astype("float32")

    def __len__(self):
        return len(self.x)

    def __getitem__(self, index):
        x = to_tensor(self.x[index])
        y = to_tensor(self.y[index])
        return x, y


class TimeSplitter:
    def __init__(self, x, y, window_size):
        N, T, F = x.shape
        self.x_chunked = []
        self.y_chunked = []
        for start_t in range(0, T, window_size):  # this could be rolling!!!!
            end_t = start_t + window_size
            self.x_chunked.append(x[:, start_t:end_t])
            self.y_chunked.append(y[:, start_t:end_t])
        self.order = np.arange(len(self.x_chunked))

    def __len__(self):
        return len(self.order)

    def __getitem__(self, index):
        return self.x_chunked[index], self.y_chunked[index]


def corr_loss(targ, pred):
    targ_mean = targ.mean(axis=0)
    pred_mean = pred.mean(axis=0)
    num = ((targ - targ_mean) * (pred - pred_mean)).sum(axis=0)
    den = (
        ((targ - targ_mean) ** 2).sum(axis=0) * ((pred - pred_mean) ** 2).sum(axis=0)
    ) ** 0.5
    avg_corr = (num / den).mean()
    return 1 - avg_corr


def corr_exp_loss(targ, pred):
    return torch.exp(corr_loss(targ, pred))
