import importlib
import os
import sys
import inspect
from pathlib import Path

import pynvml
import hydra
from omegaconf import DictConfig

from src.server.fedavg import FedAvgServer

FLBENCH_ROOT = Path(__file__).parent.absolute()
if FLBENCH_ROOT not in sys.path:
    sys.path.append(FLBENCH_ROOT.as_posix())


from src.utils.tools import parse_args


@hydra.main(config_path="config", config_name="defaults", version_base=None)
def main(config: DictConfig):
    method_name = config.method.lower()

    try:
        fl_method_server_module = importlib.import_module(f"src.server.{method_name}")
    except:
        raise ImportError(f"Can't import `src.server.{method_name}`.")

    module_attributes = inspect.getmembers(fl_method_server_module)
    server_class = [
        attribute
        for attribute in module_attributes
        if attribute[0].lower() == method_name + "server"
    ][0][1]

    get_method_hyperparams_func = getattr(server_class, f"get_hyperparams", None)

    ARGS = parse_args(config, method_name, get_method_hyperparams_func)

    # target method is not inherited from FedAvgServer
    if server_class.__bases__[0] != FedAvgServer and server_class != FedAvgServer:
        parent_server_class = server_class.__bases__[0]
        if hasattr(parent_server_class, "get_hyperparams"):
            get_parent_method_hyperparams_func = getattr(
                parent_server_class, f"get_hyperparams", None
            )
            # class name: <METHOD_NAME>Server, only want <METHOD_NAME>
            parent_method_name = parent_server_class.__name__.lower()[:-6]
            # extract the hyperparameters of the parent method
            PARENT_ARGS = parse_args(
                config, parent_method_name, get_parent_method_hyperparams_func
            )
            setattr(ARGS, parent_method_name, getattr(PARENT_ARGS, parent_method_name))

    if ARGS.mode == "parallel":
        import ray

        num_available_gpus = ARGS.parallel.num_gpus
        num_available_cpus = ARGS.parallel.num_cpus
        if num_available_gpus is None:
            pynvml.nvmlInit()
            num_total_gpus = pynvml.nvmlDeviceGetCount()
            if "CUDA_VISIBLE_DEVICES" in os.environ.keys():
                num_available_gpus = min(
                    len(os.environ["CUDA_VISIBLE_DEVICES"].split(",")), num_total_gpus
                )
            else:
                num_available_gpus = num_total_gpus
        if num_available_cpus is None:
            num_available_cpus = os.cpu_count()
        try:
            ray.init(
                address=ARGS.parallel.ray_cluster_addr,
                namespace=method_name,
                num_cpus=num_available_cpus,
                num_gpus=num_available_gpus,
                ignore_reinit_error=True,
            )
        except ValueError:
            # have existing cluster
            # then no pass num_cpus and num_gpus
            ray.init(
                address=ARGS.parallel.ray_cluster_addr,
                namespace=method_name,
                ignore_reinit_error=True,
            )

        cluster_resources = ray.cluster_resources()
        ARGS.parallel.num_cpus = cluster_resources["CPU"]
        ARGS.parallel.num_gpus = cluster_resources["GPU"]

    server = server_class(args=ARGS)
    server.run()


if __name__ == "__main__":
    main()
