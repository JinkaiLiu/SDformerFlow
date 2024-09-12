import torch
from .Spiking_swin_transformer3D import Spiking_SwinTransformer3D_v2, MS_Spiking_SwinTransformer3D_v2
from ..STSwinNet.STSwinNet import STT_MultiResUNet,STTFlowNet
from .SNN_models import *
from torch import nn
from spikingjelly.activation_based import layer, functional

if torch.cuda.is_available():
    dev_0 = "cpu"
    dev_1 = "cpu"
    dev_2 = "cpu"
else:
    dev_0 = "cpu"
    dev_1 = "cpu"
    dev_2 = "cpu"

class spiking_former_encoder(nn.Module):
    swin_type = Spiking_SwinTransformer3D_v2
    #without projections
    def __init__(
            self,
            arc_type = "swinv2",
            patch_embed_type = "PatchEmbedLocal",
            img_size=(240,320),
            patch_size=(32, 2, 2),
            in_chans=128,
            embed_dim=96,
            depths=[2, 2, 6],
            num_heads=[3, 6, 12],
            window_size=[2, 7, 7],
            pretrained_window_size=[0, 0, 0],
            mlp_ratio=4.,
            patch_norm=False,
            out_indices=(0, 1, 2),
            frozen_stages=-1,
            norm = None,
            spikformer_norm = None,
            pol_in_channel = False,
            **spiking_kwargs
    ):
        super(spiking_former_encoder, self).__init__()

        self.num_blocks = in_chans // patch_size[0]
        # if pol_in_channel:
        #     self.num_blocks = self.num_blocks * 2
        # self.num_blocks = 1
        # self.out_num_depths = self.num_blocks - 1
        # self.block_channel = block_channel

        self.img_size = img_size
        self.patch_size = patch_size
        self.in_chans = in_chans
        self.embed_dim = embed_dim
        self.depths = depths
        self.num_heads = num_heads
        self.patch_norm = patch_norm
        self.window_size = window_size
        self.mlp_ratio = mlp_ratio
        self.out_indices = out_indices
        self.frozen_stages = frozen_stages
        self.num_encoders = len(self.depths)
        self.out_channels = [self.embed_dim * (2 ** i) for i in range(self.num_encoders)]
        self.spikformer_norm = spikformer_norm


        self.swin3d = self.swin_type(
            arc_type=arc_type,
            embed_type=patch_embed_type,
            img_size=self.img_size,
            patch_size=self.patch_size,
            in_chans=self.in_chans,
            embed_dim=self.embed_dim,
            depths=self.depths,
            num_heads=self.num_heads,
            window_size=self.window_size,
            pretrained_window_size=pretrained_window_size,
            mlp_ratio=self.mlp_ratio,
            drop_rate=0.,
            attn_drop_rate=0.,
            drop_path_rate=0.2,
            norm_layer=self.spikformer_norm,
            out_indices=self.out_indices,
            frozen_stages=self.frozen_stages,
            norm=norm, # norm for the resnet ANN
            **spiking_kwargs
        )

        # self.patches_T = self.num_blocks
        # self.patch_T = self.patches_T // self.num_blocks  # 1
        # self.projections = self.build_projections()





    def forward(self, inputs):

        features = self.swin3d(inputs)

        outs = []

        #concatenate encoder features along temporal bins and project to B,C,H,W
        for i in range(self.num_encoders): #swin number
        #     out_layer_i = []
        #     features_i = features[i].chunk(self.num_blocks, 2)
        #     #print(features_i[0].shape)
        #     B, C, T, H, W = features_i[0].shape
        #     # features_i = features_i.reshape(B, -1, H, W)
        #     for k in range(self.num_blocks):
        #         feature_k = features_i[k].reshape(B, -1, H, W)  # B,C,H,W
        #         out_k = self.projections[i][k](feature_k)
        #         out_layer_i.append(out_k)
        #     out_i = torch.cat(out_layer_i, dim=1) #for each encoder cat 4 blocks featuremaps
            out_i = features[i].permute(2, 0, 1, 3, 4)
            outs.append(out_i) #C W/2 H/2   2C W/4 H/4 4c ...


        return outs

class MS_spiking_former_encoder(spiking_former_encoder):
    swin_type = MS_Spiking_SwinTransformer3D_v2



class Spikingformer_MultiResUNet(SpikingMultiResUNet):
    """
    full spiking neurons

    """
    pol_channel = False
    encoder_block = spiking_former_encoder
    upsample_4 = False

    #sew
    def __init__(self, unet_kwargs, stt_kwargs):
        unet_kwargs.pop("spiking_feedforward_block_type", None)
        super().__init__(**unet_kwargs)

        self.arc_type = stt_kwargs["use_arc"][0]
        self.patch_embed_type = stt_kwargs["use_arc"][1]
        self.num_bins_events = unet_kwargs['num_bins']
        self.depths=[int(i) for i in stt_kwargs["swin_depths"]]
        self.num_heads=[int(i) for i in stt_kwargs["swin_num_heads"]]
        assert len(self.depths) == self.num_encoders
        assert len(self.num_heads) == self.num_encoders
        self.patch_size=[int(i) for i in stt_kwargs["swin_patch_size"]]
        self.out_indices=[int(i) for i in stt_kwargs["swin_out_indices"]]
        self.window_size = [int(i) for i in stt_kwargs["window_size"]]
        self.pretrained_window_size =  [int(i) for i in stt_kwargs["pretrained_window_size"]]
        self.mlp_ratio = stt_kwargs["mlp_ratio"]
        self.input_size = stt_kwargs["input_size"]
        self.spikformer_norm = stt_kwargs["norm"] if "norm" in stt_kwargs else unet_kwargs["spiking_neuron"]["spike_norm"]


        self.encoder_output_sizes = [
            int(self.base_num_channels * pow(self.channel_multiplier, i)) for i in range(self.num_encoders)
        ]
        self.encoder_input_sizes = self.encoder_output_sizes.copy()
        self.encoder_input_sizes.insert(0,self.base_num_channels)
        self.encoder_input_sizes.pop()
        self.max_num_channels = self.encoder_output_sizes[-1]

        #self.max_num_channels = self.base_num_channels * pow(2, self.num_encoders-1)

        # self.num_channel_spikes = config["num_channel_spikes"]

        self.resblocks = self.build_resblocks()
        self.decoders = self.build_multires_prediction_decoders()
        self.preds = self.build_multires_prediction_layer()

        #print('----- ', self.num_heads)

        self.encoders = self.encoder_block(
            arc_type=self.arc_type,
            patch_embed_type=self.patch_embed_type,
            img_size=self.input_size,
            patch_size=self.patch_size,
            in_chans=self.num_bins_events,
            embed_dim=self.base_num_channels,
            depths=self.depths,
            num_heads=self.num_heads,
            window_size=self.window_size,
            pretrained_window_size=self.pretrained_window_size,
            mlp_ratio=self.mlp_ratio,
            out_indices=self.out_indices,
            norm=self.norm,
            spikformer_norm=self.spikformer_norm,
            pol_in_channel= self.pol_channel,
            **self.spiking_kwargs
        )
        self.preds_out=nn.ModuleList()
        for i in range(self.num_encoders):
            self.preds_out.append(neuron.IFNode(v_threshold = float('inf'), v_reset = 0.))

    def build_encoders(self):
        pass

    def forward(self, x):
        """
        :param x: N x num_input_channels x H x W
        :return: [N x num_output_channels x H x W for i in range(self.num_encoders)]
        """



        # encoder
        blocks = self.encoders(x)
        x = blocks[-1]

        # out_plot = x.detach()
        # plot_2d_feature_map(out_plot[0, :,...])

        # xs = x.chunk(self.steps, 1)
        # x = torch.stack(list(xs), dim=1).permute(1, 0, 2, 3, 4)  #

        # residual blocks T B C H W

        for i, resblock in enumerate(self.resblocks):
            x = resblock(x)
            # spiking_rates["res" + str(i)] = torch.mean((x != 0).float())

        # decoder and multires predictions
        predictions = []
        flow_pred = []
        for i, (decoder, pred) in enumerate(zip(self.decoders, self.preds)):
            x = self.skip_ftn(x, blocks[self.num_encoders - i - 1],dim=2)
            if i > 0:
                x = self.skip_ftn(predictions[-1], x,dim=2)
            x = decoder(x)
            # spiking_rates["decoder" + str(i)] = torch.mean((x != 0).float())

            # pred_out = []

            # for i in range(self.steps):
            #     pred_i = pred(x[i])
            #     pred_i = pred_i.unsqueeze(0)
            #     pred_out.append(pred_i)
            # pred_out = torch.cat(pred_out,dim=0)
            pred_out = pred(x)
            predictions.append(pred_out)
        # for i,pred in enumerate(predictions):
        #     self.preds_out[i](pred)
        #     flow = self.preds_out[i].v
        #     flow_pred.append(flow)


        return predictions

    def flops(self):
        flops = 0
        #encoder
        flops += self.encoders.swin3d.flops()
        H, W = self.encoders.swin3d.patch_embed.patches_resolution #96 72
        H = H // 2 ** (self.num_encoders-1)
        W = W // 2 ** (self.num_encoders-1)
        #residual blocks
        flops +=  2* self.max_num_channels * self.max_num_channels *3 *3  * H * W *self.num_residual_blocks
        #decoder and multires predictions
        decoder_output_sizes = reversed(self.encoder_input_sizes)
        decoder_input_sizes = reversed(self.encoder_output_sizes)
        for i, (input_size, output_size) in enumerate(zip(decoder_input_sizes, decoder_output_sizes)):
            prediction_channels = 0 if i == 0 else self.num_output_channels
            H = H * 2
            W = W * 2
            flops += (2 * input_size + prediction_channels) * output_size * H * W * self.kernel_size * self.kernel_size
            #bn
            flops += output_size *H * W
            flops += output_size * self.num_output_channels * H * W
            #bn
            flops += self.num_output_channels *H * W


        return flops


    def record_flops(self):
        flops_record = {}
        #encoder
        flops_record["en"] = self.encoders.swin3d.record_flops()
        H, W = self.encoders.swin3d.patch_embed.patches_resolution #96 72
        H = H // 2 ** (self.num_encoders-1)
        W = W // 2 ** (self.num_encoders-1)
        #residual blocks
        for i in range(self.num_residual_blocks):
            flops_record["res" + str(i) +"conv0"]  =  self.max_num_channels * self.max_num_channels *3 *3  * H * W
            flops_record["res" + str(i) + "conv1"] = self.max_num_channels * self.max_num_channels * 3 * 3 * H * W
            #decoder and multires predictions
        decoder_output_sizes = reversed(self.encoder_input_sizes)
        decoder_input_sizes = reversed(self.encoder_output_sizes)
        for i, (input_size, output_size) in enumerate(zip(decoder_input_sizes, decoder_output_sizes)):
            prediction_channels = 0 if i == 0 else self.num_output_channels
            H = H * 2
            W = W * 2
            flops_record["decoder" + str(i)] = (2 * input_size + prediction_channels) * output_size * H * W * self.kernel_size * self.kernel_size
            #bn
            # flops += output_size *H * W
            flops_record["pred" + str(i)] = output_size * self.num_output_channels * H * W
            #bn
            # flops += self.num_output_channels *H * W


        return flops_record



class MS_Spikingformer_MultiResUNet(Spikingformer_MultiResUNet):
    pol_channel = False
    encoder_block = MS_spiking_former_encoder
    ff_type = MS_SpikingConvEncoderLayer
    res_type = MS_ResBlock
    upsample_type = MS_SpikingDecoderLayer
    transpose_type = MS_SpikingTransposeDecoderLayer
    pred_type = MS_SpikingPredLayer
    w_scale_pred = 0.01




class SpikingformerFlowNet(STTFlowNet):

    """

    3 encoders

    encoder: convlstm
    decoder

    """
    unet_type = Spikingformer_MultiResUNet
    recurrent_block_type = "none"
    num_en = 3
    def init_weights(self):
        def _init_weights(m):
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
                if isinstance(m, nn.Linear) and m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.LayerNorm) or isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.bias, 0)
                nn.init.constant_(m.weight, 1.0)
            elif isinstance(m, nn.Conv2d):
                nn.init.xavier_uniform_(m.weight)

        self.apply(_init_weights)

    def forward(self, x, log=False):
        """
        :param event_tensor: N x num_bins x H x W   normalized t (-1 1)

        :param event_cnt: N x 4 x H x W per-polarity event cnt and average timestamp
        :param log: log activity
        :return: output dict with list of [N x 2 X H X W] (x, y) displacement within event_tensor.
        """




        # x = torch.transpose(x, 1, 2)
        # pad size for input
        # factor = {'h':2, 'w':2} # patch size for l0
        # pad_crop = CropSize(W, H, factor)
        # if (H % factor['h'] != 0) or (W % factor['w'] != 0):
        #     x = pad_crop.pad(x)
        H, W = x.shape[-2],x.shape[-1]
        multires_flow = self.sttmultires_unet.forward(x)

        # log att
        if log:
            attns = self.sttmultires_unet.encoders.swin3d.get_layer_attention_scores(x)
        else:
            attns = None

        flow_list = []


        for flow in multires_flow:
        #     #TODO: change sum to lif neuron accumulation , how to scale the flow
            flow = torch.sum(flow, dim = 0)
            flow_list.append(
                torch.nn.functional.interpolate(
                    flow,
                    scale_factor=(
                        H / flow.shape[-2],
                        W / flow.shape[-1],
                    )
                )
            )




        # flow = torch.sum(multires_flow[-1], dim = 0)
        # # flow = multires_flow[-1][-1]
        # flow_list.append(torch.nn.functional.interpolate(
        #             flow,
        #             scale_factor=(
        #                 H / flow.shape[-2],
        #                 W / flow.shape[-1],
        #             ),
        #      )
        # )
        # flow_list.append(torch.sum(multires_flow[-1], dim=0))





        return {"flow": flow_list, "attn": attns}

    def flops(self):
        return self.sttmultires_unet.flops()

    def record_flops(self):
        return self.sttmultires_unet.record_flops()

class MS_SpikingformerFlowNet(SpikingformerFlowNet):

    """

    3 encoders

    encoder: convlstm
    decoder

    """
    unet_type = MS_Spikingformer_MultiResUNet

class MS_SpikingformerFlowNet_en4(SpikingformerFlowNet):
    unet_type = MS_Spikingformer_MultiResUNet
    num_en = 4


