      subroutine openfile()
      
      use muc_mod 
      integer error	
	
	open(file='ErrorLog.dat',unit=911,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening ErrorLog.dat'
	   stop
	endif

	open(file='network.dat',unit=41,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening network.dat'
	   stop
	endif

	open(file='demand.dat',unit=42,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening demand.dat'
	   stop
	endif

	open(file='scenario.dat',unit=43,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening scenario.dat'
	   stop
	endif

	open(file='LkVolms.dat',unit=31,status='unknown',iostat=error) 
	if(error.ne.0)then
         write(911,*) 'Error when opening LinkVolumes.dat'
	   stop
	endif

	open(file='control.dat',unit=44,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening control.dat'
	   stop
	endif

	open(file='ramp.dat',unit=45,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening ramp.dat'
	   stop
	endif

	open(file='incident.dat',unit=46,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening incident.dat'
	   stop
	endif

	open(file='movement.dat',unit=47,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening movement.dat'
	   stop
	endif

	open(file='leftcap.dat',unit=48,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening leftcap.dat'
	   stop
	endif

	open(file='vms.dat',unit=49,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening vms.dat'
	   stop
	endif

	open(file='bus.dat',unit=50,status='old',iostat=error) 

	if(error.ne.0) then
         write(911,*) 'Error when opening bus.dat'
	   stop
	endif

	open(file='pricing.dat',unit=51,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening pricing.dat'
	   stop
	endif

	open(file='origin.dat',unit=52,status='old',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening origin.dat'
	   stop
	endif

	open(file='destination.dat',unit=53,status='old',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening destination.dat'
	   stop
	endif

	open(file='demand_truck.dat',unit=54,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening demand_truck.dat'
	   stop
	endif

	open(file='demand_HOV.dat',unit=61,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening demand_HOV.dat'
	   stop
	endif

	open(file='TrafficFlowModel.dat',unit=55,status=
     +  'old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening TrfficFlowModel.dat'
	   stop
	endif

	open(file='StopCap4Way.dat',unit=56,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening StopCap4Way.dat'
	   stop
	endif

	open(file='StopCap2Way.dat',unit=57,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening StopCap2Way.dat'
	   stop
	endif

	open(file='YieldCap.dat',unit=60,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening YieldCap.dat'
	   stop
	endif

	open(file='WorkZone.dat',unit=58,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening WorkZone.dat'
	   stop
	endif

    	open(file='GradeLengthPCE.dat',unit=59,status='old',iostat=error) 
	if(error.ne.0) then
         write(911,*) 'Error when opening GradeLengthPCE.dat'
	   stop
	endif

	open(file='system.dat',unit=95,status='old',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening system.dat'
	   stop
	endif

	open(file='output_option.dat',unit=101,status='old',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening output_option.dat'
	   stop
	endif

      open(file='vehicle.dat',unit=500,status='unknown',iostat=error)
	if(error.ne.0)then
         write(911,*) 'Error when opening vehicle.dat'
	   stop
	endif

	open(file='path.dat',unit=550,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening path.dat'
	   stop
	endif

c	open(file='Executing',unit=912,status='unknown',iostat=error)
c	if(error.ne.0) then
c         write(911,*) 'Error when opening executing.dat'
c	   stop
c	endif

c	write(912,*) 'DYNASPART-P IS RUNNING....' 
c	close(912)

	open(file='VehTrajectory.dat',unit=18,status='unknown',
     +  iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening VehTrajectory.dat'
	   stop
	endif

	open(file='BusTrajectory.dat',unit=188,status='unknown',
     +  iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening BusTrajectory.dat'
	   stop
	endif

      	open(file='SummaryStat.dat',unit=666,status='unknown',
     +  iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening SummaryStat.dat'
	   stop
	endif

	open(file='OutMUC.dat',unit=180,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening OutMUC.dat'
	   stop
	endif

 	open(file='fort.600',unit=600,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening fort.600'
	   stop
	endif

	open(file='fort.700',unit=700,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening fort.700'
	   stop
	endif

	open(file='fort.800',unit=800,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening fort.800'
	   stop
	endif

	open(file='fort.900',unit=900,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening fort.900'
	   stop
	endif
	
      return
      end
