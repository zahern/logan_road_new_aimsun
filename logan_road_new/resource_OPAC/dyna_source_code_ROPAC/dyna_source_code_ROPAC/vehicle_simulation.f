      	subroutine vehicle_simulation(l,t,endtime)
c --
c -- This subroutine is the main subroutine for the vehicle simulation part
c -- of DYNASMART.
c --
c -- This subroutine is called from loop every simulation interval.
c -- This subroutine calls the following subroutines
c --	a. vehicle_loading
c --  b. vehicle_moving
c --	c. vehicle_transfer
c --	d. link_performance
c --
c -- INPUT :
c --  l : the current simualtion interval number.
c --  t: current clock time
c --
      	use muc_mod
        use vector_mod	!Alex: unnecessary 
c --
      tend=t+tii
c --
c -- tend: the end of this interval
c --
c -- vehicle loading
c --
c	if(iteration.gt.0)
c	print *, 'Alex11100'
c --
      call vehicle_loading(t)
c	if(iteration.gt.0)
c	print *, 'Alex11200'
c --
c -- vehicle moving
c --
      call vehicle_moving(t,endtime)
c	if(iteration.gt.0)
c	print *, 'Alex11300'
c --
c -- vehicle transfer
c --
      call vehicle_transfer(l,t,tend)
c --
c	if(iteration.gt.0)
c	print *, 'Alex11400'
c --
c --  update the speed in traffic flow model
      call flow_model_update
c --
C	if(iteration.gt.0)
c	print *, 'Alex11500'	
c --
c --  call penalty_calculation to update the penlaties.
c --
      call penalty_calculation(l)
c --
C	if(iteration.gt.0)
c	print *, 'Alex11600'
c --
c -- output link information
c --
      call link_performance(l,t,tend)
c --
C	if(iteration.gt.0)
c	print *, 'Alex11700'
c --
      return
      end
